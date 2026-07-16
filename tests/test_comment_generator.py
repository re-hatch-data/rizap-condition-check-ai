from src.comment_generator import SYSTEM_PROMPT, build_prompt


def test_system_prompt_frames_reference_knowledge_as_tendency_not_fact():
    assert "傾向" in SYSTEM_PROMPT
    assert "医療的な診断として扱わないこと" in SYSTEM_PROMPT
    # 週150〜300分ガイドライン(⑨)は、日次kcalデータと単位・期間が噛み合わないため不採用
    assert "150" not in SYSTEM_PROMPT
    # 就寝/起床時刻の規則性(⑤)は一般化した表現のみ採用し、社会的ジェットラグの具体的な閾値は使わない
    assert "2時間" not in SYSTEM_PROMPT


def _metric(value, pre_start_mean=None, post_start_mean=None, sd_dev=None, flagged=False):
    return {
        "value": value,
        "pre_start_mean": pre_start_mean,
        "post_start_mean": post_start_mean,
        "sd_dev": sd_dev,
        "flagged": flagged,
    }


def test_build_prompt_includes_flagged_metric_and_length_instruction():
    context = {
        "date": "2026-06-15",
        "missing_days": 0,
        "metrics": {"QOLスコア": _metric(20, post_start_mean=50.0, sd_dev=-3.2, flagged=True)},
    }

    prompt = build_prompt(context, min_len=40, max_len=60)

    assert "QOLスコア" in prompt
    assert "【フラグ】" in prompt
    assert "40〜60字" in prompt


def test_build_prompt_includes_trend_section_when_pre_and_post_available():
    context = {
        "date": "2026-07-09",
        "missing_days": 0,
        "metrics": {"QOLスコア": _metric(48, pre_start_mean=40.0, post_start_mean=55.0, sd_dev=-1.1)},
    }

    prompt = build_prompt(context, min_len=40, max_len=60)

    assert "施策開始後の変化" in prompt
    assert "開始前平均=40" in prompt
    assert "開始後平均=55" in prompt
    assert "+15.0" in prompt


def test_build_prompt_omits_trend_section_when_pre_start_missing():
    context = {
        "date": "2026-07-09",
        "missing_days": 0,
        "metrics": {"QOLスコア": _metric(48, post_start_mean=55.0, sd_dev=-1.1)},
    }

    prompt = build_prompt(context, min_len=40, max_len=60)

    assert "施策開始後の変化" not in prompt
    assert "本日の状態" in prompt


def test_build_prompt_includes_form_answers():
    context = {
        "date": "2026-07-09",
        "missing_days": 0,
        "metrics": {"QOLスコア": _metric(48, post_start_mean=44.0, sd_dev=-1.1)},
        "form_answers": {
            "Q1. 今朝の体調・疲労感": "4",
            "Q3. 本日のお食事の予定・懸念": "夜に会食・飲み会の予定あり",
        },
    }

    prompt = build_prompt(context, min_len=40, max_len=60)

    assert "前日アンケート回答" in prompt
    assert "夜に会食・飲み会の予定あり" in prompt


def test_build_prompt_without_form_answers_has_no_form_section():
    context = {
        "date": "2026-07-09",
        "missing_days": 0,
        "metrics": {"QOLスコア": _metric(48, post_start_mean=44.0, sd_dev=-1.1)},
    }

    prompt = build_prompt(context, min_len=40, max_len=60)

    assert "アンケート回答" not in prompt


def test_build_prompt_formats_time_and_sleep_metrics():
    context = {
        "date": "2026-07-09",
        "missing_days": 0,
        "metrics": {
            "就寝時刻": _metric(24.52, post_start_mean=23.8, sd_dev=1.5),
            "総睡眠min": _metric(370.0, post_start_mean=390.0, sd_dev=-0.8),
            "睡眠効率": _metric(0.94, post_start_mean=0.9, sd_dev=0.1),
        },
    }

    prompt = build_prompt(context, min_len=60, max_len=120)

    assert "就寝時刻: 当日=0:31" in prompt
    assert "総睡眠min: 当日=370分(6.2時間)" in prompt
    assert "睡眠効率: 当日=94%" in prompt


def test_build_prompt_skips_missing_values():
    context = {
        "date": "2026-06-15",
        "missing_days": 1,
        "metrics": {"QOLスコア": _metric(None)},
    }

    prompt = build_prompt(context, min_len=40, max_len=60)

    assert "QOLスコア" not in prompt
