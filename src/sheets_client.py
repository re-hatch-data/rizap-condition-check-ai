"""Google Drive / Sheets アクセス。

被験者ごとの「コンディションチェック」スプレッドシートを Drive フォルダから解決し、
SOXAI_daily シートの読み取り・コメント列の書き込みを行う。

認証は「ユーザーもログインできるRIZAP側Googleアカウント」を使う方針のため、
サービスアカウントへのフォルダ共有ではなく、そのアカウントでの1回限りのOAuth認可
（`scripts/generate_oauth_token.py`）で発行したトークンファイルを使う。
トークンファイルが無い環境（別方式に切り替えた場合など）では、通常のADC
（GOOGLE_APPLICATION_CREDENTIALS やアタッチ済みサービスアカウント）にフォールバックする。
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


def get_or_create_worksheet(sh: gspread.Spreadsheet, title: str, rows: int = 100, cols: int = 10):
    try:
        return sh.worksheet(title)
    except gspread.WorksheetNotFound:
        return sh.add_worksheet(title=title, rows=rows, cols=cols)


def align_comments_to_dates(date_cells: list[str], comments_by_date: dict[str, str]) -> list[str]:
    """シート上のA列（日付セル）の並びに合わせて、コメントを行順のリストにする。

    処理側のDataFrameは日付昇順ソート＋不正日付行の除外を行うため、シートの行順とは
    一致しない可能性がある。行番号ではなく日付をキーに突き合わせることでズレを防ぐ。
    日付として解釈できないセルや、コメントが無い日付は空文字を入れる。
    """
    aligned = []
    for cell in date_cells:
        ts = pd.to_datetime(cell, errors="coerce")
        aligned.append("" if pd.isna(ts) else comments_by_date.get(ts.strftime("%Y-%m-%d"), ""))
    return aligned


def write_comment_column(
    sheets_svc,
    sh: gspread.Spreadsheet,
    sheet_name: str,
    comment_header: str,
    comments_by_date: dict[str, str],
) -> None:
    """SOXAI_daily の日付列（A列）の隣（B列）にコメント列を挿入し、A列の日付と
    突き合わせてコメントを書き込む。元データ列（C列以降）は折りたたむ。
    """
    ws = sh.worksheet(sheet_name)
    sheet_id = ws.id
    n_cols = ws.col_count

    # 同一日にリトライ実行した場合など、既にコメント列が入っていれば列挿入をスキップする
    # (SOXAI Ring側が再構築した直後は毎回このヘッダーが無い状態から始まる)
    already_present = ws.acell("B1").value == comment_header
    if not already_present:
        requests = [
            {
                "insertDimension": {
                    "range": {
                        "sheetId": sheet_id,
                        "dimension": "COLUMNS",
                        "startIndex": 1,
                        "endIndex": 2,
                    },
                    "inheritFromBefore": False,
                }
            }
        ]
        sheets_svc.spreadsheets().batchUpdate(
            spreadsheetId=sh.id, body={"requests": requests}
        ).execute()
        n_cols += 1

    date_cells = ws.col_values(1)[1:]  # ヘッダー行を除いたA列
    comments = align_comments_to_dates(date_cells, comments_by_date)
    values = [[comment_header]] + [[c] for c in comments]
    sheets_svc.spreadsheets().values().update(
        spreadsheetId=sh.id,
        range=f"'{sheet_name}'!B1:B{len(values)}",
        valueInputOption="RAW",
        body={"values": values},
    ).execute()

    _collapse_columns(sheets_svc, sh.id, sheet_id, start_index=2, end_index=n_cols + 1)


def _collapse_columns(sheets_svc, spreadsheet_id: str, sheet_id: int, start_index: int, end_index: int) -> None:
    """元データ列（コメント列より後ろ）をグループ化して折りたたむ。失敗しても致命的ではないので握りつぶす。"""
    group_range = {
        "sheetId": sheet_id,
        "dimension": "COLUMNS",
        "startIndex": start_index,
        "endIndex": end_index,
    }
    try:
        sheets_svc.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": [{"addDimensionGroup": {"range": group_range}}]},
        ).execute()
        sheets_svc.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "requests": [
                    {
                        "updateDimensionGroup": {
                            "dimensionGroup": {"range": group_range, "depth": 1, "collapsed": True},
                            "fields": "collapsed",
                        }
                    }
                ]
            },
        ).execute()
    except Exception:
        logger.warning("列の折りたたみに失敗しました（無視して続行）", exc_info=True)
