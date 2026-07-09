import pandas as pd

from src.comment_store import compute_row_hash

TARGET_METRICS = ["QOLスコア", "活動スコア"]


def test_same_values_produce_same_hash():
    row_a = pd.Series({"QOLスコア": 70, "活動スコア": 55})
    row_b = pd.Series({"QOLスコア": 70, "活動スコア": 55})

    assert compute_row_hash(row_a, TARGET_METRICS) == compute_row_hash(row_b, TARGET_METRICS)


def test_changed_value_produces_different_hash():
    row_a = pd.Series({"QOLスコア": 70, "活動スコア": 55})
    row_b = pd.Series({"QOLスコア": 65, "活動スコア": 55})

    assert compute_row_hash(row_a, TARGET_METRICS) != compute_row_hash(row_b, TARGET_METRICS)
