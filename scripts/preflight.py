"""権限・API有効化の事前診断ツール。

RIZAP側でIAM付与後、本番デプロイ前に実行して「どこまで通っているか」を確認する。

使い方:
    python -m scripts.preflight                 # 認証・Drive・Sheets・Vertex AIの疎通確認
    python -m scripts.preflight --ask 1名分のコメント生成をE2Eで試す
"""

import argparse
import logging
import sys

from src.config import DAILY_SHEET, TARGET_METRICS, settings, validate_settings
from src.metrics import compute_flags, row_context

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def check(label: str, fn) -> bool:
    try:
        result = fn()
        logger.info("✅ %s%s", label, f"（{result}）" if result else "")
        return True
    except Exception as e:  # noqa: BLE001
        logger.error("❌ %s: %s", label, e)
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ask", action="store_true", help="被験者1名分のコメント生成までE2Eで試す")
    args = parser.parse_args()

    missing = validate_settings()
    if missing:
        logger.error("❌ 必須環境変数が未設定です: %s", ", ".join(missing))
        return 1

    from src.sheets_client import get_google_services, list_subject_spreadsheets, load_daily_dataframe

    ok = True
    drive_svc = sheets_svc = gc = None

    def _auth():
        nonlocal drive_svc, sheets_svc, gc
        drive_svc, sheets_svc, gc = get_google_services()
        return None

    ok &= check("Google認証（ADC解決）", _auth)

    subjects = []

    def _drive():
        nonlocal subjects
        subjects = list_subject_spreadsheets(drive_svc, settings.cond_folder_id)
        return f"{len(subjects)}名分のスプレッドシートを検出"

    ok &= check(f"Drive: COND_FOLDER_ID配下の被験者フォルダ一覧取得（{settings.cond_folder_id}）", _drive)

    if not subjects:
        logger.error("被験者フォルダが1件も見つかりませんでした。共有設定を確認してください。")
        return 1

    df_holder = {}

    def _sheets():
        df = load_daily_dataframe(gc, subjects[0]["spreadsheet_id"], DAILY_SHEET)
        df_holder["df"] = df
        return f"{subjects[0]['folder_name']}: {len(df)}行"

    ok &= check("Sheets: SOXAI_daily読み取り", _sheets)

    def _vertex():
        from google.genai import types

        from src.comment_generator import build_client

        client = build_client(settings)
        resp = client.models.generate_content(
            model=settings.gemini_model,
            contents="OK とだけ返してください",
            config=types.GenerateContentConfig(max_output_tokens=16),
        )
        return (resp.text or "").strip()

    ok &= check(f"Vertex AI: Gemini呼び出し（{settings.gemini_model} @ {settings.gcp_location}）", _vertex)

    if args.ask and "df" in df_holder and not df_holder["df"].empty:
        from src.comment_generator import build_client, generate_comment

        df = compute_flags(df_holder["df"], TARGET_METRICS, settings.sd_threshold)
        last_row = df.iloc[-1]
        context = row_context(last_row, TARGET_METRICS)
        client = build_client(settings)
        comment = generate_comment(
            client, settings.gemini_model, context, settings.comment_min_len, settings.comment_max_len
        )
        logger.info("--- E2E生成結果（%s / %s） ---\n%s", subjects[0]["folder_name"], context["date"], comment)

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
