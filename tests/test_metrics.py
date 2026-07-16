import pandas as pd

from src.config import DATE_COLUMN
from src.metrics import (
    FLAG_SUFFIX,
    MISSING_DAYS_COLUMN,
    POST_START_MEAN_SUFFIX,
    PRE_START_MEAN_SUFFIX,
    SD_BASIS_SUFFIX,
    SD_DEV_SUFFIX,
    compute_flags,
    row_context,
)

TARGET_METRICS = ["QOLスコア"]


def _make_df(values, dates):
    return pd.DataFrame(
        {
            DATE_COLUMN: dates,
            "ユーザーID": ["u1"] * len(values),
            "QOLスコア": values,
        }
    )


def test_stable_values_are_not_flagged():
    dates = pd.date_range("2026-06-01", periods=10, freq="D")
    values = [70, 71, 69, 70, 72, 69, 70, 71, 70, 69]
    df = compute_flags(_make_df(values, dates), TARGET_METRICS, sd_threshold=2.0)

    assert not df[f"QOLスコア{FLAG_SUFFIX}"].fillna(False).any()


def test_outlier_is_flagged():
    dates = pd.date_range("2026-06-01", periods=11, freq="D")
    values = [70, 71, 69, 70, 72, 69, 70, 71, 70, 69, 20]  # 最終日に大きく落ち込む
    df = compute_flags(_make_df(values, dates), TARGET_METRICS, sd_threshold=2.0)

    assert bool(df.iloc[-1][f"QOLスコア{FLAG_SUFFIX}"]) is True


def test_missing_days_are_counted():
    dates = pd.to_datetime(["2026-06-01", "2026-06-02", "2026-06-06"])  # 3日分の空白
    values = [70, 71, 72]
    df = compute_flags(_make_df(values, dates), TARGET_METRICS, sd_threshold=2.0)

    assert df.iloc[0][MISSING_DAYS_COLUMN] == 0
    assert df.iloc[1][MISSING_DAYS_COLUMN] == 0
    assert df.iloc[2][MISSING_DAYS_COLUMN] == 3


def test_sleep_metrics_zero_treated_as_missing():
    dates = pd.date_range("2026-06-01", periods=3, freq="D")
    df = pd.DataFrame(
        {
            DATE_COLUMN: dates,
            "ユーザーID": ["u1"] * 3,
            "総睡眠min": [370, 0, 380],  # 2日目はリング未装着で未計測
        }
    )

    out = compute_flags(df, ["総睡眠min"], sd_threshold=2.0)

    assert pd.isna(out.iloc[1]["総睡眠min"])
    assert out.iloc[2]["総睡眠min"] == 380


def test_bedtime_converted_to_hours_across_midnight():
    dates = pd.date_range("2026-06-01", periods=2, freq="D")
    df = pd.DataFrame(
        {
            DATE_COLUMN: dates,
            "ユーザーID": ["u1"] * 2,
            "総睡眠min": [370, 380],
            "就寝時刻": ["2026-06-01T23:16:00+09:00", "2026-06-03T00:31:00+09:00"],
        }
    )

    out = compute_flags(df, ["就寝時刻"], sd_threshold=2.0)

    # 23:16 → 23.27h、深夜0:31は前日夜と連続比較できるよう 24.52h になる
    assert abs(out.iloc[0]["就寝時刻"] - (23 + 16 / 60)) < 0.01
    assert abs(out.iloc[1]["就寝時刻"] - (24 + 31 / 60)) < 0.01


def test_row_context_shape():
    dates = pd.date_range("2026-06-01", periods=6, freq="D")
    values = [70, 71, 69, 70, 72, 69]
    df = compute_flags(_make_df(values, dates), TARGET_METRICS, sd_threshold=2.0)

    ctx = row_context(df.iloc[-1], TARGET_METRICS)
    assert "QOLスコア" in ctx["metrics"]
    assert ctx["metrics"]["QOLスコア"]["value"] == 69
    assert "missing_days" in ctx


def test_no_training_start_date_treats_all_rows_as_post_start():
    """training_start_date未指定時は、従来通り全履歴を基準にする（開始前平均は計算しない）。"""
    dates = pd.date_range("2026-06-01", periods=6, freq="D")
    values = [70, 71, 69, 70, 72, 69]
    df = compute_flags(_make_df(values, dates), TARGET_METRICS, sd_threshold=2.0)

    assert pd.isna(df.iloc[-1][f"QOLスコア{PRE_START_MEAN_SUFFIX}"])
    assert pd.notna(df.iloc[-1][f"QOLスコア{POST_START_MEAN_SUFFIX}"])


def test_pre_and_post_start_means_are_split_at_training_start_date():
    dates = pd.date_range("2026-06-01", periods=12, freq="D")
    # 開始前(6/1-6/5)は低め、開始後(6/6-)は高めの値
    values = [40, 42, 41, 39, 40, 60, 61, 59, 60, 62, 58, 61]
    df = compute_flags(
        _make_df(values, dates), TARGET_METRICS, sd_threshold=2.0, training_start_date="2026-06-06"
    )

    pre_mean = df.iloc[-1][f"QOLスコア{PRE_START_MEAN_SUFFIX}"]
    assert abs(pre_mean - 40.4) < 0.1

    # 開始前の行には開始後平均・フラグが計算されない
    pre_start_row = df[df[DATE_COLUMN] < "2026-06-06"].iloc[0]
    assert pd.isna(pre_start_row[f"QOLスコア{POST_START_MEAN_SUFFIX}"])
    assert pd.isna(pre_start_row[f"QOLスコア{FLAG_SUFFIX}"])


def test_unparseable_training_start_date_falls_back_to_all_history():
    """名簿の開始日が解釈できない値でも、エラーにせず全履歴基準にフォールバックすること。"""
    dates = pd.date_range("2026-06-01", periods=6, freq="D")
    values = [70, 71, 69, 70, 72, 69]

    df = compute_flags(_make_df(values, dates), TARGET_METRICS, sd_threshold=2.0, training_start_date="未定")

    assert pd.isna(df.iloc[-1][f"QOLスコア{PRE_START_MEAN_SUFFIX}"])
    assert pd.notna(df.iloc[-1][f"QOLスコア{POST_START_MEAN_SUFFIX}"])


def test_sd_detection_uses_pre_start_baseline_during_warmup():
    """施策開始直後（開始後データ5日未満）でも、開始前データが十分あれば
    開始前平均を暫定基準にして異常検知が働くこと。"""
    dates = pd.date_range("2026-06-01", periods=8, freq="D")
    # 開始前(6/1-6/7)は安定して70前後、開始翌日(6/8)に大きく落ち込む
    values = [70, 71, 69, 70, 72, 69, 70, 20]
    df = compute_flags(
        _make_df(values, dates), TARGET_METRICS, sd_threshold=2.0, training_start_date="2026-06-08"
    )

    last = df.iloc[-1]
    assert pd.notna(last[f"QOLスコア{SD_DEV_SUFFIX}"])
    assert last[f"QOLスコア{SD_BASIS_SUFFIX}"] == "開始前平均"
    assert bool(last[f"QOLスコア{FLAG_SUFFIX}"]) is True


def test_sd_basis_switches_to_post_start_mean_after_warmup():
    dates = pd.date_range("2026-06-01", periods=12, freq="D")
    values = [70, 71, 69, 70, 72, 60, 61, 59, 60, 62, 58, 61]
    df = compute_flags(
        _make_df(values, dates), TARGET_METRICS, sd_threshold=2.0, training_start_date="2026-06-06"
    )

    # 開始後6日目以降は開始後平均が基準になる
    assert df.iloc[-1][f"QOLスコア{SD_BASIS_SUFFIX}"] == "開始後平均"
    ctx = row_context(df.iloc[-1], TARGET_METRICS)
    assert ctx["metrics"]["QOLスコア"]["sd_basis"] == "開始後平均"


def test_post_start_average_only_uses_post_start_history():
    """開始後平均の計算に開始前のデータが混ざらないこと。"""
    dates = pd.date_range("2026-06-01", periods=11, freq="D")
    # 開始前(6/1-6/5)は極端に低い値。開始後(6/6-)の平均計算に混ざると値が歪む
    values = [0, 0, 0, 0, 0, 60, 61, 59, 60, 62, 61]
    df = compute_flags(
        _make_df(values, dates), TARGET_METRICS, sd_threshold=2.0, training_start_date="2026-06-06"
    )

    last_post_mean = df.iloc[-1][f"QOLスコア{POST_START_MEAN_SUFFIX}"]
    # 開始後の値(60前後)のみで平均されていれば60付近、開始前の0が混ざれば大きく下振れするはず
    assert last_post_mean > 55
