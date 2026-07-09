"""前日比・7日平均比・SD逸脱度・欠測日数の計算。

被験者ごとのスコア水準は個人差が大きいため、絶対値ではなく本人の過去データを
基準にした相対指標（SD逸脱度＝本人の平均・標準偏差からの乖離）でフラグ化する。
"""

import pandas as pd

from src.config import DATE_COLUMN, SLEEP_METRICS, TIME_METRICS, TOTAL_SLEEP_COLUMN

PREV_DIFF_SUFFIX = "_前日比"
VS_7D_SUFFIX = "_7日平均比"
SD_DEV_SUFFIX = "_SD逸脱度"
FLAG_SUFFIX = "_フラグ"
MISSING_DAYS_COLUMN = "欠測日数"


def compute_flags(df: pd.DataFrame, target_metrics: list[str], sd_threshold: float) -> pd.DataFrame:
    """日付昇順に並べ替えたうえで、指標ごとの前日比・7日平均比・SD逸脱度・フラグ列を追加する。"""
    if df.empty or DATE_COLUMN not in df.columns:
        return df

    df = df.copy()
    df[DATE_COLUMN] = pd.to_datetime(df[DATE_COLUMN], errors="coerce")
    df = df.dropna(subset=[DATE_COLUMN]).sort_values(DATE_COLUMN).reset_index(drop=True)

    # 就寝/起床時刻(ISO日時文字列)を時刻(時間の小数)へ変換し、「普段より遅い」を数値比較できるようにする
    for col in TIME_METRICS:
        if col in df.columns:
            df[col] = _time_to_hours(df[col], evening=(col == "就寝時刻"))

    # リング未装着等で睡眠が計測されていない日(総睡眠min=0)は、0ではなく欠測として扱う
    # (0のまま平均やSDに入れると本人の平常値が大きく歪むため)
    if TOTAL_SLEEP_COLUMN in df.columns:
        no_sleep = pd.to_numeric(df[TOTAL_SLEEP_COLUMN], errors="coerce").fillna(0) <= 0
        for metric in SLEEP_METRICS:
            if metric in df.columns:
                df.loc[no_sleep, metric] = pd.NA

    for metric in target_metrics:
        if metric not in df.columns:
            continue
        series = pd.to_numeric(df[metric], errors="coerce")
        df[metric] = series

        prev = series.shift(1)
        df[f"{metric}{PREV_DIFF_SUFFIX}"] = series - prev

        rolling_7d = series.shift(1).rolling(window=7, min_periods=3).mean()
        df[f"{metric}{VS_7D_SUFFIX}"] = series - rolling_7d

        # 「本人平均」は当日を含まない、それまでの全履歴（最低5日分たまってから判定開始）
        personal_mean = series.shift(1).expanding(min_periods=5).mean()
        personal_std = series.shift(1).expanding(min_periods=5).std()
        sd_dev = (series - personal_mean) / personal_std.replace(0, pd.NA)
        df[f"{metric}{SD_DEV_SUFFIX}"] = sd_dev
        df[f"{metric}{FLAG_SUFFIX}"] = sd_dev.abs() >= sd_threshold

    df[MISSING_DAYS_COLUMN] = _missing_day_counts(df[DATE_COLUMN])
    return df


def _time_to_hours(series: pd.Series, *, evening: bool) -> pd.Series:
    """日時文字列を時刻(時間の小数)にする。就寝時刻は深夜0時台を24h+として扱い、
    前日夜(23時台)との連続比較・平均計算ができるようにする。"""
    ts = pd.to_datetime(series, errors="coerce")
    hours = ts.dt.hour + ts.dt.minute / 60.0
    if evening:
        hours = hours.where(hours >= 15, hours + 24)
    return hours


def _missing_day_counts(dates: pd.Series) -> pd.Series:
    """直前の計測日からの欠測日数（連続していれば0）。"""
    gaps = dates.diff().dt.days.sub(1).clip(lower=0)
    if len(gaps) > 0:
        gaps.iloc[0] = 0
    return gaps.fillna(0).astype(int)


def row_context(row: pd.Series, target_metrics: list[str]) -> dict:
    """1行分の指標状況を、プロンプト生成用の辞書にまとめる。"""
    metrics_ctx = {}
    for metric in target_metrics:
        if metric not in row:
            continue
        flag_value = row.get(f"{metric}{FLAG_SUFFIX}")
        metrics_ctx[metric] = {
            "value": row.get(metric),
            "prev_diff": row.get(f"{metric}{PREV_DIFF_SUFFIX}"),
            "vs_7d_avg": row.get(f"{metric}{VS_7D_SUFFIX}"),
            "sd_dev": row.get(f"{metric}{SD_DEV_SUFFIX}"),
            "flagged": bool(flag_value) if pd.notna(flag_value) else False,
        }
    return {
        "date": row.get(DATE_COLUMN),
        "missing_days": int(row.get(MISSING_DAYS_COLUMN, 0)),
        "metrics": metrics_ctx,
    }
