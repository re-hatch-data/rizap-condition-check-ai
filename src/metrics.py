"""施策開始前平均・開始後平均・当日SD逸脱度・欠測日数の計算。

被験者ごとのスコア水準は個人差が大きいため、絶対値ではなく本人の過去データを
基準にした相対指標でフラグ化する。比較軸は2つ:
  1. 施策開始前平均 → 施策開始後平均（施策全体の効果を示す長期トレンド）
  2. 当日の値 → 開始後平均からのSD逸脱度（いつも通りの異常検知。基準点は
     「全履歴平均」ではなく「施策開始後の平均」に変更した）
"""

import logging

import pandas as pd

from src.config import DATE_COLUMN, SLEEP_METRICS, TIME_METRICS, TOTAL_SLEEP_COLUMN

logger = logging.getLogger(__name__)

PRE_START_MEAN_SUFFIX = "_開始前平均"
POST_START_MEAN_SUFFIX = "_開始後平均"
SD_DEV_SUFFIX = "_SD逸脱度"
SD_BASIS_SUFFIX = "_SD基準"
FLAG_SUFFIX = "_フラグ"
MISSING_DAYS_COLUMN = "欠測日数"

# SD逸脱度の判定を始めるのに必要な最低日数（expandingのmin_periodsと開始前フォールバックで共用）
MIN_BASELINE_DAYS = 5


def compute_flags(
    df: pd.DataFrame,
    target_metrics: list[str],
    sd_threshold: float,
    training_start_date: str | None = None,
) -> pd.DataFrame:
    """日付昇順に並べ替えたうえで、指標ごとの開始前平均・開始後平均・SD逸脱度・フラグ列を追加する。

    training_start_date が None の場合は全期間を「開始後」扱いとする
    （開始前平均は計算されず、SD逸脱度は従来通り全履歴基準になる）。
    """
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

    # 名簿は手入力のため、解釈できない日付はエラーにせず全履歴基準へフォールバックする
    start_ts = pd.to_datetime(training_start_date, errors="coerce") if training_start_date else None
    if start_ts is not None and pd.isna(start_ts):
        logger.warning(
            "トレーニング開始日を日付として解釈できません: %r（YYYY-MM-DD形式を想定）。"
            "全履歴基準にフォールバックします。",
            training_start_date,
        )
        start_ts = None
    is_post_start = df[DATE_COLUMN] >= start_ts if start_ts is not None else pd.Series(True, index=df.index)

    for metric in target_metrics:
        if metric not in df.columns:
            continue
        series = pd.to_numeric(df[metric], errors="coerce")
        df[metric] = series

        pre_start_values = series[~is_post_start]
        df[f"{metric}{PRE_START_MEAN_SUFFIX}"] = pre_start_values.mean() if len(pre_start_values) else pd.NA

        post_idx = df.index[is_post_start]
        post_series = series.loc[post_idx].reset_index(drop=True)
        # 「開始後平均」は当日を含まない、開始日以降のそれまでの平均（最低5日分たまってから判定開始）
        post_mean = post_series.shift(1).expanding(min_periods=MIN_BASELINE_DAYS).mean()
        post_std = post_series.shift(1).expanding(min_periods=MIN_BASELINE_DAYS).std()

        # 開始後データが5日分たまるまでの間は、開始前データが十分あれば開始前平均・SDを
        # 暫定基準にする（施策開始直後＝最も見たい時期に異常検知の空白を作らないため）。
        # どちらを基準にしたかはSD基準列に残し、プロンプト側で表記を切り替える
        basis = pd.Series("開始後平均", index=post_series.index)
        baseline_mean, baseline_std = post_mean, post_std
        if pre_start_values.count() >= MIN_BASELINE_DAYS:
            basis[post_mean.isna()] = "開始前平均"
            baseline_mean = post_mean.fillna(pre_start_values.mean())
            baseline_std = post_std.fillna(pre_start_values.std())
        sd_dev = (post_series - baseline_mean) / baseline_std.replace(0, pd.NA)

        df.loc[post_idx, f"{metric}{POST_START_MEAN_SUFFIX}"] = post_mean.values
        df.loc[post_idx, f"{metric}{SD_DEV_SUFFIX}"] = sd_dev.values
        df.loc[post_idx, f"{metric}{SD_BASIS_SUFFIX}"] = basis.values
        df.loc[post_idx, f"{metric}{FLAG_SUFFIX}"] = (sd_dev.abs() >= sd_threshold).values

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
            "pre_start_mean": row.get(f"{metric}{PRE_START_MEAN_SUFFIX}"),
            "post_start_mean": row.get(f"{metric}{POST_START_MEAN_SUFFIX}"),
            "sd_dev": row.get(f"{metric}{SD_DEV_SUFFIX}"),
            "sd_basis": row.get(f"{metric}{SD_BASIS_SUFFIX}"),
            "flagged": bool(flag_value) if pd.notna(flag_value) else False,
        }
    return {
        "date": row.get(DATE_COLUMN),
        "missing_days": int(row.get(MISSING_DAYS_COLUMN, 0)),
        "metrics": metrics_ctx,
    }
