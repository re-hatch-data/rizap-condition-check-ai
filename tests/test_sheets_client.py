from src.sheets_client import align_comments_to_dates


def test_aligns_by_date_regardless_of_sheet_order():
    date_cells = ["2026-06-03", "2026-06-01", "2026-06-02"]  # シートが日付順でないケース
    comments = {
        "2026-06-01": "A",
        "2026-06-02": "B",
        "2026-06-03": "C",
    }

    assert align_comments_to_dates(date_cells, comments) == ["C", "A", "B"]


def test_unparseable_date_and_missing_comment_become_empty():
    date_cells = ["2026-06-01", "合計", "2026-06-05"]
    comments = {"2026-06-01": "A"}

    assert align_comments_to_dates(date_cells, comments) == ["A", "", ""]


def test_accepts_slash_format_dates():
    date_cells = ["2026/06/01"]
    comments = {"2026-06-01": "A"}

    assert align_comments_to_dates(date_cells, comments) == ["A"]
