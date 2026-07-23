"""バッチ本体。

COND_FOLDER_ID 配下の全被験者スプレッドシートについて、日付ごとのAIコメント
（特徴的な値の指摘＋今日の過ごし方アドバイス）を生成し、各スプレッドシート内の
`AIコメント_ログ` シートに保存する。SOXAI_daily 自体には書き込まない
（SOXAI Ringが毎朝delete→再作成するため。追加シートは削除対象外なので消えない）。
Cloud Run Jobs から Cloud Scheduler 経由で毎朝9:00(JST)に起動される
（SOXAI Ring同期の完了実績が8:15〜8:40頃のため）。当日分を生成済みの実行は
被験者ごとのログシート確認だけで即終了する冪等な作りで、手動再実行や
ジョブの自動リトライで多重に走っても安全。
"""

import logging
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from src.comment_generator import build_client, generate_comment
from src.comment_store import CommentStore, compute_row_hash
from src.config import (
    DAILY_SHEET,
    DATE_COLUMN,
    FORM_SHEET,
    ROSTER_SHEET_NAME,
    TARGET_METRICS,
    UID_COLUMN,
    settings,
    validate_settings,
)
from src.metrics import compute_flags, row_context
from src.rate_limit import with_rate_limit_retry
from src.sheets_client import (
    get_google_services,
    list_subject_spreadsheets,
    load_daily_dataframe,
    load_form_answers,
    load_training_start_dates,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def process_subject(gc, genai_client, subject: dict, training_start_dates: dict[str, str]) -> None:
    name = subject["folder_name"]
    spreadsheet_id = subject["spreadsheet_id"]
    logger.info("=== %s (%s) ===", name, spreadsheet_id)

    sh = with_rate_limit_retry(gc.open_by_key, spreadsheet_id)
    store = CommentStore(sh)

    # 当日分を生成済みならこれ以上読まずに抜ける。手動再実行やジョブの自動リトライが
    # 生成中の実行と重なっても、同じ日付を二重生成してログシートを書き戻し合う事故を
    # 防ぐ（SOXAI_daily等の再読み込みも省ける）。当日中のデータ訂正はこのスキップにより
    # 反映されないが、翌朝の実行でハッシュ不一致として再生成される
    today_str = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d")
    if store.has_date(today_str):
        logger.info("  本日(%s)分は生成済みです。スキップします。", today_str)
        return

    df = load_daily_dataframe(sh, DAILY_SHEET)
    if df.empty or DATE_COLUMN not in df.columns:
        logger.warning("  SOXAI_dailyが空、または想定した列がありません。スキップします。")
        return

    # 施策開始日はマスター名簿(soxai_id基準)から引く。名簿に無い被験者はNoneのまま
    # compute_flagsに渡り、従来通り全履歴基準にフォールバックする
    subject_uid = str(df[UID_COLUMN].iloc[0]) if UID_COLUMN in df.columns else ""
    training_start_date = training_start_dates.get(subject_uid)
    df = compute_flags(df, TARGET_METRICS, settings.sd_threshold, training_start_date)

    form_answers = load_form_answers(sh, FORM_SHEET)

    # HISTORY_DAYSより古い日付は新規生成しない（初回実行時に全履歴分のGemini呼び出しが走るのを防ぐ）
    cutoff = df[DATE_COLUMN].max() - pd.Timedelta(days=settings.history_days)

    generated_count = 0
    for _, row in df.iterrows():
        date_str = row[DATE_COLUMN].strftime("%Y-%m-%d")
        uid = str(row.get(UID_COLUMN, ""))
        # アンケートは常に前日分を参照する（実行時刻の関係で当日分は全員提出済みとは
        # 限らないため、日によって当日/前日が混在しないよう統一する。前日分は実行時点で
        # 確定しているため、後から提出されて再生成が必要になることもない）
        prev_date_str = (row[DATE_COLUMN] - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        answers = form_answers.get(prev_date_str, {})
        # 施策開始日もハッシュに含める（名簿の開始日が後から入力・修正された場合に、
        # 基準が変わった過去日付をHISTORY_DAYSの範囲で自動再生成するため）
        extra = f"{sorted(answers.items())}|start={training_start_date or ''}"
        row_hash = compute_row_hash(row, TARGET_METRICS, extra=extra)

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

    training_start_dates = load_training_start_dates(gc, settings.roster_sheet_id, ROSTER_SHEET_NAME)
    logger.info("マスター名簿から施策開始日を取得: %d名分", len(training_start_dates))

    failures = []
    for i, subject in enumerate(subjects):
        if i > 0:
            # 被験者ごとに複数のSheets API呼び出しが発生するため、間隔を空けずに
            # 全員分を連続実行すると「1分あたりの読み取りリクエスト数」の既定クォータに
            # 容易に達してしまう(実測)。with_rate_limit_retryでの再試行と合わせ、
            # そもそも制限に達しにくくする
            time.sleep(2)
        try:
            process_subject(gc, genai_client, subject, training_start_dates)
        except Exception:
            logger.exception("処理に失敗しました: %s", subject.get("folder_name"))
            failures.append(subject.get("folder_name"))

    if failures:
        logger.error("失敗した被験者（%d名）: %s", len(failures), ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
