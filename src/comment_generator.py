"""Agent Platform（旧Vertex AI）経由でGeminiを呼び出し、日次コメントを生成する。

コメント内容は「特徴的な値の指摘＋今日の過ごし方アドバイス」。
Geminiは純正のGoogleモデルのため、API（aiplatform.googleapis.com）を有効化するだけで
利用できる（Model Garden経由のパートナーモデルのような追加の利用規約同意が不要）。
"""

import logging

import pandas as pd
from google import genai
from google.genai import types

from src.config import TIME_METRICS, TOTAL_SLEEP_COLUMN, Settings

logger = logging.getLogger(__name__)

# 一般的に知られている傾向（査読付き研究・公的機関のガイドライン等、確度の高い情報源のみを採用。
# 2026-07-15調査。詳細な出典・不採用とした項目の理由は docs/setup-checklist.md 参照）。
# あくまで「傾向」の参考知識としてGeminiに渡すのみで、判定ロジック(閾値等)には一切使わない。
REFERENCE_TENDENCIES = (
    "\n\n【参考知識：一般的に知られている傾向（断定的な基準や医療的な診断として扱わないこと。"
    "自然に触れられる場合のみ参考にし、無理にすべて盛り込む必要はない）】\n"
    "- 入眠までの時間は、平均的にはおよそ15分前後とされ、それより明らかに長い状態が続く場合は"
    "寝つきの困難さのサインとされる傾向がある\n"
    "- 普段と異なる時刻の就寝・起床が続くと、体への負担につながりうるとされる傾向がある\n"
    "- 睡眠不足はストレスへの耐性を下げ、逆にストレスも睡眠の質に影響しうるという、"
    "互いに影響し合う関係にあるとされる\n"
    "- 1日の歩数は、成人でおよそ8,000歩程度が一つの目安とされることがある"
)

SYSTEM_PROMPT = (
    "あなたはフィットネス施設のトレーナー向けに、被験者の日次コンディションデータから"
    "一言コメントを作成するアシスタントです。"
    "与えられるのは、睡眠（総睡眠時間・深い/浅い/REM睡眠・入眠潜時・睡眠効率・就寝/起床時刻）、"
    "ストレス、活動量（歩数・活動消費kcal）の実測値です。比較の軸は2つあります。"
    "(1) 施策開始前平均→施策開始後平均：施策全体を通じた長期的な変化。"
    "(2) 当日の値の、個人平均（原則は施策開始後平均。開始直後でデータが少ない間は開始前平均）"
    "からのSD逸脱度：直近の異常検知。"
    "加えて、欠測日数と、本人の前日アンケート回答（体調の自己評価・業務負荷の想定・食事の予定など）"
    "が与えられます。"
    "アンケートは前日に回答されたものです。設問文にある「今朝」「本日」はすべて前日を指すため、"
    "当日の予定として扱ってはいけません（例:「本日の業務負荷: 高い」は前日の業務負荷が高かったという意味。"
    "「夜に会食あり」はすでに終わった前日夜の会食）。"
    "前日の状況（業務負荷・会食・体調など）の影響や疲労が当日の数値に表れていないか、"
    "という視点で参考にしてください。"
    "「特徴的な値の指摘」と「今日1日をより良く過ごすための具体的なアドバイス」を、"
    "指定された文字数の範囲内の自然な日本語（1〜2文）で書いてください。"
    "長期的な変化（施策の効果）と当日の異常値の両方が確認できる場合は、両方に触れてもかまいません。"
    "睡眠時間が短い・就寝時刻がいつもより遅い・ストレスが高い等は、"
    "トレーナーがそのまま本人への声かけに使える表現で指摘してください。"
    "アンケート回答がある日は、数値と自己申告のギャップ（本人は元気なつもりだが数値は低い等）にも着目してください。"
    "数値の羅列や絵文字、前置き・見出しは不要です。コメント本文だけを出力してください。"
    + REFERENCE_TENDENCIES
)


def build_client(settings: Settings) -> genai.Client:
    return genai.Client(vertexai=True, project=settings.gcp_project, location=settings.gcp_location)


def build_prompt(context: dict, min_len: int, max_len: int) -> str:
    lines = [
        f"日付: {context['date']}",
        f"欠測日数（直近の空白日数）: {context['missing_days']}日",
        "（min系は分、就寝/起床時刻はHH:MM表記・差分は時間、睡眠効率は%）",
    ]

    trend_lines = []
    today_lines = []
    for metric, m in context["metrics"].items():
        value = m["value"]
        if pd.isna(value):
            continue
        unit = "h" if metric in TIME_METRICS else ""

        pre = m["pre_start_mean"]
        post = m["post_start_mean"]
        if pd.notna(pre) and pd.notna(post):
            trend_lines.append(
                f"- {metric}: 開始前平均={_fmt_value(metric, pre)} → 開始後平均={_fmt_value(metric, post)}"
                f"（{_fmt_delta(metric, pre, post, unit)}）"
            )

        flag = "【フラグ】" if m["flagged"] else ""
        sd_dev = _fmt(m["sd_dev"])
        basis = m.get("sd_basis") if isinstance(m.get("sd_basis"), str) else "開始後平均"
        today_lines.append(
            f"- {metric}: 当日={_fmt_value(metric, value)} {basis}からのSD逸脱度={sd_dev} {flag}"
        )

    if trend_lines:
        lines.append("\n【施策開始後の変化】(開始前平均→開始後平均)")
        lines += trend_lines
    lines.append("\n【本日の状態】(個人平均からの逸脱)")
    lines += today_lines

    if context.get("form_answers"):
        lines.append("\n本人の前日アンケート回答（設問の「今朝」「本日」は前日を指す）:")
        for question, answer in context["form_answers"].items():
            lines.append(f"- {question}: {answer}")

    lines.append(
        f"\n{min_len}〜{max_len}字程度で、特徴的な値の指摘＋今日1日の過ごし方の具体的なアドバイスを書いてください。"
    )
    return "\n".join(lines)


def _fmt_delta(metric: str, pre, post, unit: str) -> str:
    """開始前→開始後の変化量。睡眠効率は平均表示(%)に合わせてポイント表記にする
    （生値0-1のまま+.1f整形すると+4ptの変化も「+0.0」になってしまうため）。"""
    delta = post - pre
    if metric == "睡眠効率" and pre <= 1 and post <= 1:
        return f"{delta * 100:+.1f}pt"
    return f"{delta:+.1f}{unit}"


def _fmt_value(metric: str, v) -> str:
    """指標ごとに人間が読める形へ整形する（時刻はHH:MM、睡眠効率は%、総睡眠は時間併記）。"""
    if metric in TIME_METRICS:
        total_min = round(float(v) % 24 * 60)
        return f"{total_min // 60}:{total_min % 60:02d}"
    if metric == "睡眠効率" and isinstance(v, (int, float)) and v <= 1:
        return f"{float(v) * 100:.0f}%"
    if metric == TOTAL_SLEEP_COLUMN:
        return f"{float(v):.0f}分({float(v) / 60:.1f}時間)"
    return str(v)


def _fmt(v) -> str:
    if pd.isna(v):
        return "N/A"
    return f"{v:+.1f}" if isinstance(v, (int, float)) else str(v)


def generate_comment(client: genai.Client, model: str, context: dict, min_len: int, max_len: int) -> str:
    prompt = build_prompt(context, min_len, max_len)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, max_output_tokens=300),
    )
    text = (response.text or "").strip()
    if len(text) > max_len + 10:
        logger.warning("コメントが想定より長いため切り詰めます（%d字）: %s", len(text), text)
        text = text[:max_len]
    return text
