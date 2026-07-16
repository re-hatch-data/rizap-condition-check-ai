from src.sheets_client import load_training_start_dates, parse_training_start_dates


def test_parse_training_start_dates_maps_uid_to_date():
    records = [
        {"soxai_id": "rizap_001", "氏名": "堤圭佑", "トレーニング開始日": "2026-06-07"},
        {"soxai_id": "rizap_024", "氏名": "渡邉拓哉", "トレーニング開始日": "2026-06-10"},
    ]

    result = parse_training_start_dates(records)

    assert result == {"rizap_001": "2026-06-07", "rizap_024": "2026-06-10"}


def test_parse_training_start_dates_skips_rows_missing_uid_or_date():
    records = [
        {"soxai_id": "rizap_001", "トレーニング開始日": ""},  # 未入力
        {"soxai_id": "", "トレーニング開始日": "2026-06-07"},  # uid無し
        {"soxai_id": "rizap_002", "トレーニング開始日": "2026-06-08"},  # 正常
    ]

    result = parse_training_start_dates(records)

    assert result == {"rizap_002": "2026-06-08"}


def test_parse_training_start_dates_empty_records():
    assert parse_training_start_dates([]) == {}


def test_parse_training_start_dates_strips_whitespace():
    records = [{"soxai_id": " rizap_003 ", "トレーニング開始日": " 2026-06-09 "}]

    result = parse_training_start_dates(records)

    assert result == {"rizap_003": "2026-06-09"}


class _PermissionDeniedGC:
    """名簿がSAに共有されていない場合、gspread 6.xはopen_by_keyでPermissionErrorを送出する。"""

    def open_by_key(self, key):
        raise PermissionError


def test_load_training_start_dates_falls_back_on_permission_error():
    """名簿にアクセスできなくてもジョブ全体を落とさず、空dict（全履歴基準）に倒れること。"""
    result = load_training_start_dates(_PermissionDeniedGC(), "roster-id", "被験者名簿")

    assert result == {}
