import pandas as pd

from src.config import DATE_COLUMN
from src.metrics import FLAG_SUFFIX, MISSING_DAYS_COLUMN, compute_flags, row_context

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


def test_row_context_shape():
    dates = pd.date_range("2026-06-01", periods=6, freq="D")
    values = [70, 71, 69, 70, 72, 69]
    df = compute_flags(_make_df(values, dates), TARGET_METRICS, sd_threshold=2.0)

    ctx = row_context(df.iloc[-1], TARGET_METRICS)
    assert "QOLスコア" in ctx["metrics"]
    assert ctx["metrics"]["QOLスコア"]["value"] == 69
    assert "missing_days" in ctx
