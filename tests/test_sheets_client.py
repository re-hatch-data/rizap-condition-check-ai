from src.sheets_client import parse_training_start_dates


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
