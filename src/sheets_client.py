"""Google Drive / Sheets アクセス。

被験者ごとの「コンディションチェック」スプレッドシートを Drive フォルダから解決し、
SOXAI_daily・フォームの回答シートを読み取る。コメントの出力（AIコメント_ログシート）は
comment_store が担う。

認証は既存パイプライン rizap-soxai-ring と同じサービスアカウント（soxai-runner）を
再利用する。対象スプレッドシートへのアクセス実績が既にあるSAのため、追加の共有設定が不要。
本番(Cloud Run Jobs)ではSAキーをSecret Manager経由でマウントし、
GOOGLE_APPLICATION_CREDENTIALS で渡す（通常のADC解決）。
GOOGLE_OAUTH_TOKEN_FILE にOAuthトークンファイルがある場合はそちらを優先する
（ローカル検証用のフォールバック。`scripts/generate_oauth_token.py` で生成できる）。
"""

import logging
import os
import pathlib

import gspread
import pandas as pd
from google.auth import default as google_auth_default
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials as UserCredentials
from googleapiclient.discovery import build

from src.config import FORM_TIMESTAMP_COLUMN

logger = logging.getLogger(__name__)

# Driveはフォルダ走査（読み取り）にしか使わないため readonly に絞る。
# シートへの書き込みは spreadsheets スコープで行う。
SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]

FOLDER_MIME = "application/vnd.google-apps.folder"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"

DEFAULT_OAUTH_TOKEN_FILE = "credentials/oauth-token.json"


def _load_credentials():
    token_file = os.environ.get("GOOGLE_OAUTH_TOKEN_FILE", DEFAULT_OAUTH_TOKEN_FILE)
    if pathlib.Path(token_file).exists():
        creds = UserCredentials.from_authorized_user_file(token_file, scopes=SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(GoogleAuthRequest())
        return creds
    creds, _ = google_auth_default(scopes=SCOPES)
    return creds


def get_google_services():
    """(drive_svc, sheets_svc, gspread_client) を返す。"""
    creds = _load_credentials()
    drive_svc = build("drive", "v3", credentials=creds)
    sheets_svc = build("sheets", "v4", credentials=creds)
    gc = gspread.authorize(creds)
    return drive_svc, sheets_svc, gc


def list_folder_files(drive_svc, folder_id: str, mime: str | None = None) -> list[dict]:
    """フォルダ内のファイル一覧を返す。共有ドライブにも対応。"""
    q = f"'{folder_id}' in parents and trashed=false"
    if mime:
        q += f" and mimeType='{mime}'"
    out, token = [], None
    while True:
        resp = (
            drive_svc.files()
            .list(
                q=q,
                fields="nextPageToken, files(id,name,mimeType)",
                pageSize=200,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                pageToken=token,
            )
            .execute()
        )
        out += resp.get("files", [])
        token = resp.get("nextPageToken")
        if not token:
            break
    return out


def list_subject_spreadsheets(drive_svc, cond_folder_id: str) -> list[dict]:
    """被験者フォルダを走査し、[{folder_name, spreadsheet_id, spreadsheet_name}] を返す。

    「コンディションチェック」を含むスプレッドシートを優先し、無ければ先頭のシートを使う
    （rizap-soxai-ring の build_subject_mapping と同じ選定ルール）。
    """
    subfolders = list_folder_files(drive_svc, cond_folder_id, FOLDER_MIME)
    subjects = []
    for folder in subfolders:
        sheets = list_folder_files(drive_svc, folder["id"], SHEET_MIME)
        if not sheets:
            logger.warning("スプレッドシートが見つかりません: %s", folder["name"])
            continue
        target = next((s for s in sheets if "コンディションチェック" in s["name"]), sheets[0])
        subjects.append(
            {
                "folder_name": folder["name"],
                "spreadsheet_id": target["id"],
                "spreadsheet_name": target["name"],
            }
        )
    return subjects


def load_daily_dataframe(gc: gspread.Client, spreadsheet_id: str, sheet_name: str) -> pd.DataFrame:
    """SOXAI_daily シートを DataFrame として読み込む。シートが無ければ空を返す。"""
    sh = gc.open_by_key(spreadsheet_id)
    try:
        ws = sh.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        return pd.DataFrame()
    records = ws.get_all_records()
    return pd.DataFrame(records)


def load_form_answers(sh: gspread.Spreadsheet, sheet_name: str) -> dict[str, dict[str, str]]:
    """当日アンケート（「フォームの回答 1」）を読み込み、日付(%Y-%m-%d) → {設問: 回答} を返す。

    同じ日に複数回答がある場合は後の回答で上書きする。空欄の設問と、運用情報である
    SOXAI RINGの同期状況（Q4）は除外する。シートが無ければ空dictを返す。
    """
    try:
        ws = sh.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        return {}
    answers: dict[str, dict[str, str]] = {}
    for r in ws.get_all_records():
        ts = pd.to_datetime(str(r.get(FORM_TIMESTAMP_COLUMN, "")), errors="coerce")
        if pd.isna(ts):
            continue
        qa = {
            str(q): str(a)
            for q, a in r.items()
            if q != FORM_TIMESTAMP_COLUMN and str(a).strip() and "SOXAI" not in str(q)
        }
        if qa:
            answers[ts.strftime("%Y-%m-%d")] = qa
    return answers


def get_or_create_worksheet(sh: gspread.Spreadsheet, title: str, rows: int = 100, cols: int = 10):
    try:
        return sh.worksheet(title)
    except gspread.WorksheetNotFound:
        return sh.add_worksheet(title=title, rows=rows, cols=cols)
