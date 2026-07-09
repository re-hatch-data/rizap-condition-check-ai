from src.comment_generator import build_prompt


def test_build_prompt_includes_flagged_metric_and_length_instruction():
    context = {
        "date": "2026-06-15",
        "missing_days": 0,
        "metrics": {
            "QOLスコア": {
                "value": 20,
                "prev_diff": -30.0,
                "vs_7d_avg": -25.5,
                "sd_dev": -3.2,
                "flagged": True,
            }
        },
    }

    prompt = build_prompt(context, min_len=40, max_len=60)

    assert "QOLスコア" in prompt
    assert "【フラグ】" in prompt
    assert "40〜60字" in prompt


def test_build_prompt_includes_form_answers():
    context = {
        "date": "2026-07-09",
        "missing_days": 0,
        "metrics": {
            "QOLスコア": {"value": 48, "prev_diff": 4.0, "vs_7d_avg": -10.0, "sd_dev": -1.1, "flagged": False}
        },
        "form_answers": {
            "Q1. 今朝の体調・疲労感": "4",
            "Q3. 本日のお食事の予定・懸念": "夜に会食・飲み会の予定あり",
        },
    }

    prompt = build_prompt(context, min_len=40, max_len=60)

    assert "当日アンケート回答" in prompt
    assert "夜に会食・飲み会の予定あり" in prompt


def test_build_prompt_without_form_answers_has_no_form_section():
    context = {
        "date": "2026-07-09",
        "missing_days": 0,
        "metrics": {
            "QOLスコア": {"value": 48, "prev_diff": 4.0, "vs_7d_avg": -10.0, "sd_dev": -1.1, "flagged": False}
        },
    }

    prompt = build_prompt(context, min_len=40, max_len=60)

    assert "当日アンケート回答" not in prompt


def test_build_prompt_skips_missing_values():
    context = {
        "date": "2026-06-15",
        "missing_days": 1,
        "metrics": {
            "QOLスコア": {"value": None, "prev_diff": None, "vs_7d_avg": None, "sd_dev": None, "flagged": False}
        },
    }

    prompt = build_prompt(context, min_len=40, max_len=60)

    assert "QOLスコア" not in prompt
