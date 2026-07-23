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


def _store_for_flush(entries, loaded_data_rows):
    from unittest.mock import Mock

    from src.comment_store import CommentStore

    store = CommentStore.__new__(CommentStore)
    store._entries = entries
    store._loaded_data_rows = loaded_data_rows
    store._dirty = True
    store._ws = Mock(row_count=200)
    return store


def test_flush_overwrites_without_clear():
    """clear()→update()の2段階は、clear直後の失敗でログシートが空のまま残るため使わない。"""
    entry = {"comment": "c", "hash": "h", "generated_at": "t"}
    store = _store_for_flush({("2026-07-16", "u1"): entry}, loaded_data_rows=1)

    store.flush()

    store._ws.clear.assert_not_called()
    store._ws.update.assert_called_once()
    rows = store._ws.update.call_args[0][1]
    assert rows[1][0] == "2026-07-16"


def test_flush_pads_blank_rows_when_entries_shrink():
    """読み込み時に重複キーが畳まれる等で行数が減った場合、減った分を空行で上書きして
    古い内容がシートに残らないようにする。"""
    entry = {"comment": "c", "hash": "h", "generated_at": "t"}
    store = _store_for_flush({("2026-07-16", "u1"): entry}, loaded_data_rows=3)

    store.flush()

    rows = store._ws.update.call_args[0][1]
    assert len(rows) == 4  # ヘッダー + データ1行 + 空行パディング2行
    assert rows[2] == [""] * 5
    assert rows[3] == [""] * 5
