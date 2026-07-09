"""Vertex AI経由でGeminiを呼び出し、日次コメント（特徴的な値＋一言総評）を生成する。

Geminiは純正のGoogleモデルのため、RIZAP側GCPプロジェクトでVertex AI APIを有効化するだけで
利用できる（Model Garden経由のパートナーモデルのような追加の利用規約同意が不要）。
"""

import logging

import pandas as pd
from google import genai
from google.genai import types

from src.config import Settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "あなたはフィットネス施設のトレーナー向けに、被験者の日次コンディションデータから"
    "一言コメントを作成するアシスタントです。"
    "与えられた数値・前日比・7日平均比・本人平均からのSD逸脱度・欠測日数と、"
    "本人の当日アンケート回答（体調の自己評価・業務負荷の想定・食事の予定など）をもとに、"
    "特徴的な値の指摘と一言総評を、指定された文字数の範囲内の自然な日本語1文（または2文）で書いてください。"
    "アンケート回答がある日は、数値と自己申告のギャップ（本人は元気なつもりだが数値は低い等）にも着目してください。"
    "数値の羅列や絵文字、前置き・見出しは不要です。コメント本文だけを出力してください。"
)


def build_client(settings: Settings) -> genai.Client:
    return genai.Client(vertexai=True, project=settings.gcp_project, location=settings.gcp_location)


def build_prompt(context: dict, min_len: int, max_len: int) -> str:
    lines = [f"日付: {context['date']}", f"欠測日数（直近の空白日数）: {context['missing_days']}日", "指標:"]
    for metric, m in context["metrics"].items():
        value = m["value"]
        if value is None or (isinstance(value, float) and pd.isna(value)):
            continue
        flag = "【フラグ】" if m["flagged"] else ""
        prev_diff = _fmt(m["prev_diff"])
        vs_7d = _fmt(m["vs_7d_avg"])
        sd_dev = _fmt(m["sd_dev"])
        lines.append(
            f"- {metric}: 値={value} 前日比={prev_diff} 7日平均比={vs_7d} SD逸脱度={sd_dev} {flag}"
        )
    if context.get("form_answers"):
        lines.append("本人の当日アンケート回答（コンディションチェック）:")
        for question, answer in context["form_answers"].items():
            lines.append(f"- {question}: {answer}")
    lines.append(f"\n{min_len}〜{max_len}字程度で、特徴的な値の指摘＋一言総評を書いてください。")
    return "\n".join(lines)


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
