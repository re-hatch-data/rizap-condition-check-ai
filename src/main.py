"""バッチ本体。

COND_FOLDER_ID 配下の全被験者スプレッドシートについて、日付ごとのAIコメント
（特徴的な値の指摘＋今日の過ごし方アドバイス）を生成し、各スプレッドシート内の
`AIコメント_ログ` シートに保存する。SOXAI_daily 自体には書き込まない
（SOXAI Ringが毎朝delete→再作成するため。追加シートは削除対象外なので消えない）。
Cloud Run Jobs から Cloud Scheduler 経由で毎朝（SOXAI Ring同期の後）1回実行される想定。
"""

import logging
import sys

import pandas as pd

from src.comment_generator import build_client, generate_comment
from src.comment_store import CommentStore, compute_row_hash
from src.config import (
    DAILY_SHEET,
    DATE_COLUMN,
    FORM_SHEET,
    TARGET_METRICS,
    UID_COLUMN,
    settings,
    validate_settings,
)
from src.metrics import compute_flags, row_context
from src.sheets_client import (
    get_google_services,
    list_subject_spreadsheets,
    load_daily_dataframe,
    load_form_answers,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def process_subject(gc, genai_client, subject: dict) -> None:
    name = subject["folder_name"]
    spreadsheet_id = subject["spreadsheet_id"]
    logger.info("=== %s (%s) ===", name, spreadsheet_id)

    df = load_daily_dataframe(gc, spreadsheet_id, DAILY_SHEET)
    if df.empty or DATE_COLUMN not in df.columns:
        logger.warning("  SOXAI_dailyが空、または想定した列がありません。スキップします。")
        return

    df = compute_flags(df, TARGET_METRICS, settings.sd_threshold)

    sh = gc.open_by_key(spreadsheet_id)
    store = CommentStore(sh)
    form_answers = load_form_answers(sh, FORM_SHEET)

    # HISTORY_DAYSより古い日付は新規生成しない（初回実行時に全履歴分のGemini呼び出しが走るのを防ぐ）
    cutoff = df[DATE_COLUMN].max() - pd.Timedelta(days=settings.history_days)

    generated_count = 0
    for _, row in df.iterrows():
        date_str = row[DATE_COLUMN].strftime("%Y-%m-%d")
        uid = str(row.get(UID_COLUMN, ""))
        answers = form_answers.get(date_str, {})
        # アンケート回答もハッシュに含める（ジョブ実行後に回答が提出された日は翌朝再生成される）
        row_hash = compute_row_hash(row, TARGET_METRICS, extra=str(sorted(answers.items())))

        cached = store.get(date_str, uid)
        if cached and cached["comment"] and cached["hash"] == row_hash:
            continue
        if row[DATE_COLUMN] < cutoff:
            continue

        context = row_context(row, TARGET_METRICS)
        context["form_answers"] = answers
        comment = generate_comment(
            genai_client,
            settings.gemini_model,
            context,
            settings.comment_min_len,
            settings.comment_max_len,
        )
        store.upsert(date_str, uid, comment, row_hash)
        generated_count += 1
        logger.info("  [%s] 新規生成: %s", date_str, comment)

    logger.info("  対象%d日分中 新規/更新 %d件（残りは生成済み）", len(df), generated_count)

    if settings.dry_run:
        logger.info("  DRY_RUN: 書き込みはスキップします。")
        return

    store.flush()
    logger.info("  反映完了。")


def main() -> int:
    missing = validate_settings()
    if missing:
        logger.error("必須環境変数が未設定です: %s", ", ".join(missing))
        return 1

    drive_svc, _sheets_svc, gc = get_google_services()
    genai_client = build_client(settings)

    subjects = list_subject_spreadsheets(drive_svc, settings.cond_folder_id)
    logger.info("対象被験者数: %d", len(subjects))

    failures = []
    for subject in subjects:
        try:
            process_subject(gc, genai_client, subject)
        except Exception:
            logger.exception("処理に失敗しました: %s", subject.get("folder_name"))
            failures.append(subject.get("folder_name"))

    if failures:
        logger.error("失敗した被験者（%d名）: %s", len(failures), ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
