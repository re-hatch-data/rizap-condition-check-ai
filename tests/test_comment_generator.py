import pandas as pd

from src.comment_generator import SYSTEM_PROMPT, _DISCIPLINES, _is_sane_key_result, _pick_discipline, build_prompt


def test_system_prompt_frames_reference_knowledge_as_tendency_not_fact():
    assert "傾向" in SYSTEM_PROMPT
    assert "医学的な診断" in SYSTEM_PROMPT


def test_system_prompt_forbids_diagnosis_and_treatment_language():
    """8学問分野の知見を扱うにあたっての安全ガードレールが明記されていること。"""
    assert "診断" in SYSTEM_PROMPT
    assert "断定" in SYSTEM_PROMPT
    assert "治療" in SYSTEM_PROMPT


def test_reference_tendencies_cover_all_eight_disciplines():
    disciplines = ["時間生物学", "神経科学", "運動生理学", "ホメオスタシス", "栄養学", "バイオメカニクス", "睡眠医学", "行動心理学"]
    for discipline in disciplines:
        assert discipline in SYSTEM_PROMPT, f"{discipline}がSYSTEM_PROMPTに含まれていない"


def _metric(value, pre_start_mean=None, post_start_mean=None, sd_dev=None, flagged=False, sd_basis=None):
    return {
        "value": value,
        "pre_start_mean": pre_start_mean,
        "post_start_mean": post_start_mean,
        "sd_dev": sd_dev,
        "sd_basis": sd_basis,
        "flagged": flagged,
    }


def test_build_prompt_includes_flagged_metric_and_length_instruction():
    context = {
        "date": "2026-06-15",
        "missing_days": 0,
        "metrics": {"QOLスコア": _metric(20, post_start_mean=50.0, sd_dev=-3.2, flagged=True)},
    }

    prompt = build_prompt(context, "目標テキスト", ["QOLスコア"], min_len=40, max_len=60)

    assert "QOLスコア" in prompt
    assert "【本日のKR対象】" in prompt
    assert "40〜60字" in prompt
    assert "目標テキスト" in prompt
    assert "重点分野" in prompt


def test_build_prompt_includes_trend_section_when_pre_and_post_available():
    context = {
        "date": "2026-07-09",
        "missing_days": 0,
        "metrics": {"QOLスコア": _metric(48, pre_start_mean=40.0, post_start_mean=55.0, sd_dev=-1.1)},
    }

    prompt = build_prompt(context, "目標テキスト", [], min_len=40, max_len=60)

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

    prompt = build_prompt(context, "目標テキスト", [], min_len=40, max_len=60)

    assert "施策開始後の変化" not in prompt
    assert "本日の状態" in prompt


def test_system_prompt_frames_answers_as_previous_day():
    """前日回答の設問文に含まれる「本日」を当日の予定と誤解させないための指示があること。"""
    assert "「今朝」「本日」はすべて前日を指す" in SYSTEM_PROMPT
    assert "当日の予定として扱ってはいけません" in SYSTEM_PROMPT


def test_build_prompt_labels_answers_as_previous_day():
    context = {
        "date": "2026-07-09",
        "missing_days": 0,
        "metrics": {"QOLスコア": _metric(48, post_start_mean=44.0, sd_dev=-1.1)},
        "form_answers": {"Q2. 本日の業務負荷の想定": "高い"},
    }

    prompt = build_prompt(context, "目標テキスト", [], min_len=40, max_len=60)

    assert "設問の「今朝」「本日」は前日を指す" in prompt


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

    prompt = build_prompt(context, "目標テキスト", [], min_len=40, max_len=60)

    assert "前日アンケート回答" in prompt
    assert "夜に会食・飲み会の予定あり" in prompt


def test_build_prompt_without_form_answers_has_no_form_section():
    context = {
        "date": "2026-07-09",
        "missing_days": 0,
        "metrics": {"QOLスコア": _metric(48, post_start_mean=44.0, sd_dev=-1.1)},
    }

    prompt = build_prompt(context, "目標テキスト", [], min_len=40, max_len=60)

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

    prompt = build_prompt(context, "目標テキスト", [], min_len=60, max_len=120)

    assert "就寝時刻: 当日=0:31" in prompt
    assert "総睡眠min: 当日=370分(6.2時間)" in prompt
    assert "睡眠効率: 当日=94%" in prompt


def test_build_prompt_handles_pd_na_pre_start_mean():
    """名簿に開始日が無い被験者はmetrics側が開始前平均にpd.NAを入れる。
    float(pd.NA)でクラッシュせず、トレンド欄をスキップできること。"""
    context = {
        "date": "2026-07-09",
        "missing_days": 0,
        "metrics": {"総睡眠min": _metric(370.0, pre_start_mean=pd.NA, post_start_mean=390.0, sd_dev=-0.8)},
    }

    prompt = build_prompt(context, "目標テキスト", [], min_len=40, max_len=60)

    assert "施策開始後の変化" not in prompt
    assert "総睡眠min: 当日=370分" in prompt


def test_build_prompt_sleep_efficiency_delta_in_points():
    """睡眠効率(0-1格納)の変化量が生値スケールで「+0.0」に丸まらず、ポイント表記になること。"""
    context = {
        "date": "2026-07-09",
        "missing_days": 0,
        "metrics": {"睡眠効率": _metric(0.95, pre_start_mean=0.90, post_start_mean=0.94, sd_dev=0.4)},
    }

    prompt = build_prompt(context, "目標テキスト", [], min_len=40, max_len=60)

    assert "開始前平均=90% → 開始後平均=94%" in prompt
    assert "+4.0pt" in prompt
    assert "+0.0" not in prompt


def test_build_prompt_shows_sd_basis_label():
    """施策開始直後の暫定基準（開始前平均）が、逸脱度のラベルに反映されること。"""
    context = {
        "date": "2026-07-09",
        "missing_days": 0,
        "metrics": {"QOLスコア": _metric(48, sd_dev=-2.5, flagged=True, sd_basis="開始前平均")},
    }

    prompt = build_prompt(context, "目標テキスト", ["QOLスコア"], min_len=40, max_len=60)

    assert "開始前平均からのSD逸脱度=-2.5" in prompt


def test_build_prompt_skips_missing_values():
    context = {
        "date": "2026-06-15",
        "missing_days": 1,
        "metrics": {"QOLスコア": _metric(None)},
    }

    prompt = build_prompt(context, "目標テキスト", [], min_len=40, max_len=60)

    assert "QOLスコア" not in prompt


def _key_result(situation="s", behavior="b", impact="i", keep="k", problem="p", try_="t"):
    return {
        "metric": "総睡眠min",
        "sbi": {"situation": situation, "behavior": behavior, "impact": impact},
        "kpt": {"keep": keep, "problem": problem, "try": try_},
    }


def test_is_sane_key_result_accepts_normal_length_fields():
    assert _is_sane_key_result(_key_result()) is True


def test_is_sane_key_result_rejects_runaway_field():
    """Gemini応答のフィールド内に自己言及・JSON再生成の試み等が混入し、
    異常に長くなったKRは出力崩れとみなして破棄すること。"""
    runaway = _key_result(try_="あ" * 500)
    assert _is_sane_key_result(runaway) is False


def test_pick_discipline_is_deterministic():
    assert _pick_discipline("2026-07-11", "就寝時刻") == _pick_discipline("2026-07-11", "就寝時刻")


def test_pick_discipline_varies_by_date():
    """実測: 参考知識を増やすだけでは同じ状況に対して毎回同じ観点(例:体内時計)に収束したため、
    日付が変われば重点分野も変わることで、同じ指標でも日によって異なる角度の説明を促す。"""
    picks = {_pick_discipline(f"2026-07-{d:02d}", "就寝時刻") for d in range(1, 15)}
    assert len(picks) > 1


def test_pick_discipline_stays_within_metric_relevant_subset():
    """実測: 8分野を指標に関係なく均等にローテーションすると、「ストレス」に
    「バイオメカニクス」が割り当たり、こじつけの説明になるケースがあった。
    指標ごとに関連の薄い分野を除いた候補からのみ選ぶこと。"""
    for d in range(1, 29):
        assert _pick_discipline(f"2026-07-{d:02d}", "ストレス") not in ("バイオメカニクス", "運動生理学")
        assert _pick_discipline(f"2026-07-{d:02d}", "浅睡眠min") in ("睡眠医学", "神経科学")


def test_pick_discipline_falls_back_to_full_list_for_unknown_metric():
    picks = {_pick_discipline(f"2026-07-{d:02d}", "QOLスコア") for d in range(1, 29)}
    assert picks <= set(_DISCIPLINES)


def test_build_prompt_includes_daily_discipline_hint_only_when_flagged():
    context = {
        "date": "2026-07-09",
        "missing_days": 0,
        "metrics": {"QOLスコア": _metric(48, sd_dev=-2.5, flagged=True)},
    }

    prompt = build_prompt(context, "目標テキスト", ["QOLスコア"], min_len=40, max_len=60)

    assert "今回のKRごとの重点分野" in prompt
    assert _pick_discipline("2026-07-09", "QOLスコア") in prompt


def test_build_prompt_omits_discipline_hint_when_no_flags():
    context = {
        "date": "2026-07-09",
        "missing_days": 0,
        "metrics": {"QOLスコア": _metric(48, sd_dev=0.1)},
    }

    prompt = build_prompt(context, "目標テキスト", [], min_len=40, max_len=60)

    assert "今回のKRごとの重点分野" not in prompt
