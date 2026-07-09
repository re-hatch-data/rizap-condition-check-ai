"""バッチ本体。

COND_FOLDER_ID 配下の全被験者スプレッドシートについて、SOXAI_daily の各日付行に
AIコメント（特徴的な値の指摘＋一言総評）を生成し反映する。Cloud Run Jobs から
Cloud Scheduler 経由で毎朝（SOXAI Ring同期の後）1回実行される想定。
"""

import logging
import sys

from src.comment_generator import build_client, generate_comment
from src.comment_store import CommentStore, compute_row_hash
from src.config import (
    COMMENT_COLUMN_HEADER,
    DAILY_SHEET,
    DATE_COLUMN,
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
    write_comment_column,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def process_subject(gc, sheets_svc, claude_client, subject: dict) -> None:
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

    comments = []
    generated_count = 0
    for _, row in df.iterrows():
        date_str = row[DATE_COLUMN].strftime("%Y-%m-%d")
        uid = str(row.get(UID_COLUMN, ""))
        row_hash = compute_row_hash(row, TARGET_METRICS)

        cached = store.get(date_str, uid)
        if cached and cached["hash"] == row_hash and cached["comment"]:
            comments.append(cached["comment"])
            continue

        context = row_context(row, TARGET_METRICS)
        comment = generate_comment(
            claude_client,
            settings.claude_model,
            context,
            settings.comment_min_len,
            settings.comment_max_len,
        )
        store.upsert(date_str, uid, comment, row_hash)
        comments.append(comment)
        generated_count += 1
        logger.info("  [%s] 新規生成: %s", date_str, comment)

    logger.info("  対象%d件中 新規/更新 %d件（残りはキャッシュを再利用）", len(comments), generated_count)

    if settings.dry_run:
        logger.info("  DRY_RUN: 書き込みはスキップします。")
        return

    write_comment_column(sheets_svc, sh, DAILY_SHEET, COMMENT_COLUMN_HEADER, comments)
    store.flush()
    logger.info("  反映完了。")


def main() -> int:
    missing = validate_settings()
    if missing:
        logger.error("必須環境変数が未設定です: %s", ", ".join(missing))
        return 1

    drive_svc, sheets_svc, gc = get_google_services()
    claude_client = build_client(settings)

    subjects = list_subject_spreadsheets(drive_svc, settings.cond_folder_id)
    logger.info("対象被験者数: %d", len(subjects))

    failures = []
    for subject in subjects:
        try:
            process_subject(gc, sheets_svc, claude_client, subject)
        except Exception:
            logger.exception("処理に失敗しました: %s", subject.get("folder_name"))
            failures.append(subject.get("folder_name"))

    if failures:
        logger.error("失敗した被験者（%d名）: %s", len(failures), ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
