"""Vertex AI経由でClaudeを呼び出し、日次コメント（特徴的な値＋一言総評）を生成する。

Anthropic直APIキーは使わず、RIZAP側GCPプロジェクトのVertex AI権限のみで完結させる
（anthropic[vertex] の AnthropicVertex クライアントを使用）。
"""

import logging

import pandas as pd
from anthropic import AnthropicVertex

from src.config import Settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "あなたはフィットネス施設のトレーナー向けに、被験者の日次コンディションデータから"
    "一言コメントを作成するアシスタントです。"
    "与えられた数値・前日比・7日平均比・本人平均からのSD逸脱度・欠測日数をもとに、"
    "特徴的な値の指摘と一言総評を、指定された文字数の範囲内の自然な日本語1文（または2文）で書いてください。"
    "数値の羅列や絵文字、前置き・見出しは不要です。コメント本文だけを出力してください。"
)


def build_client(settings: Settings) -> AnthropicVertex:
    return AnthropicVertex(project_id=settings.gcp_project, region=settings.gcp_location)


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
    lines.append(f"\n{min_len}〜{max_len}字程度で、特徴的な値の指摘＋一言総評を書いてください。")
    return "\n".join(lines)


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "N/A"
    return f"{v:+.1f}" if isinstance(v, (int, float)) else str(v)


def generate_comment(client: AnthropicVertex, model: str, context: dict, min_len: int, max_len: int) -> str:
    prompt = build_prompt(context, min_len, max_len)
    response = client.messages.create(
        model=model,
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if len(text) > max_len + 10:
        logger.warning("コメントが想定より長いため切り詰めます（%d字）: %s", len(text), text)
        text = text[:max_len]
    return text
