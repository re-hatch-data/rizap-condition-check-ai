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


def test_changed_extra_produces_different_hash():
    """開始日やアンケート回答（extra）が変わったら再生成対象になること。"""
    row = pd.Series({"QOLスコア": 70, "活動スコア": 55})

    hash_without = compute_row_hash(row, TARGET_METRICS, extra="[]|start=")
    hash_with = compute_row_hash(row, TARGET_METRICS, extra="[]|start=2026-06-07")

    assert hash_without != hash_with


def test_has_date_checks_any_uid():
    from src.comment_store import CommentStore

    store = CommentStore.__new__(CommentStore)
    store._entries = {("2026-07-16", "rizap_001"): {"comment": "c", "hash": "h", "generated_at": ""}}

    assert store.has_date("2026-07-16") is True
    assert store.has_date("2026-07-15") is False
