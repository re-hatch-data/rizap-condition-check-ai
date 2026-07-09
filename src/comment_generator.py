"""Vertex AI経由でGeminiを呼び出し、日次コメント（特徴的な値の指摘＋今日の過ごし方アドバイス）を生成する。

Geminiは純正のGoogleモデルのため、RIZAP側GCPプロジェクトでVertex AI APIを有効化するだけで
利用できる（Model Garden経由のパートナーモデルのような追加の利用規約同意が不要）。
"""

import logging

import pandas as pd
from google import genai
from google.genai import types

from src.config import TIME_METRICS, TOTAL_SLEEP_COLUMN, Settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "あなたはフィットネス施設のトレーナー向けに、被験者の日次コンディションデータから"
    "一言コメントを作成するアシスタントです。"
    "与えられるのは、睡眠（総睡眠時間・深い/浅い/REM睡眠・入眠潜時・睡眠効率・就寝/起床時刻）、"
    "ストレス、活動量（歩数・活動消費kcal）の実測値と、その前日比・7日平均比・"
    "本人平均からのSD逸脱度・欠測日数、および本人の当日アンケート回答"
    "（体調の自己評価・業務負荷の想定・食事の予定など）です。"
    "「特徴的な値の指摘」と「今日1日をより良く過ごすための具体的なアドバイス」を、"
    "指定された文字数の範囲内の自然な日本語（1〜2文）で書いてください。"
    "睡眠時間が短い・就寝時刻がいつもより遅い・ストレスが高い等は、"
    "トレーナーがそのまま本人への声かけに使える表現で指摘してください。"
    "アンケート回答がある日は、数値と自己申告のギャップ（本人は元気なつもりだが数値は低い等）にも着目してください。"
    "数値の羅列や絵文字、前置き・見出しは不要です。コメント本文だけを出力してください。"
)


def build_client(settings: Settings) -> genai.Client:
    return genai.Client(vertexai=True, project=settings.gcp_project, location=settings.gcp_location)


def build_prompt(context: dict, min_len: int, max_len: int) -> str:
    lines = [
        f"日付: {context['date']}",
        f"欠測日数（直近の空白日数）: {context['missing_days']}日",
        "指標（min系は分、就寝/起床時刻はHH:MM表記・差分は時間、睡眠効率は%）:",
    ]
    for metric, m in context["metrics"].items():
        value = m["value"]
        if value is None or (isinstance(value, float) and pd.isna(value)):
            continue
        flag = "【フラグ】" if m["flagged"] else ""
        unit = "h" if metric in TIME_METRICS else ""
        prev_diff = _fmt(m["prev_diff"])
        vs_7d = _fmt(m["vs_7d_avg"])
        sd_dev = _fmt(m["sd_dev"])
        lines.append(
            f"- {metric}: 値={_fmt_value(metric, value)}"
            f" 前日比={prev_diff}{unit} 7日平均比={vs_7d}{unit} SD逸脱度={sd_dev} {flag}"
        )
    if context.get("form_answers"):
        lines.append("本人の当日アンケート回答（コンディションチェック）:")
        for question, answer in context["form_answers"].items():
            lines.append(f"- {question}: {answer}")
    lines.append(
        f"\n{min_len}〜{max_len}字程度で、特徴的な値の指摘＋今日1日の過ごし方の具体的なアドバイスを書いてください。"
    )
    return "\n".join(lines)


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
    if v is None or (isinstance(v, float) and pd.isna(v)):
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
