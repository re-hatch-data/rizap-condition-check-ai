"""コメントの永続キャッシュ（`AIコメント_ログ`シート）。

対象の SOXAI_daily シートは既存パイプライン（rizap-soxai-ring）により毎朝
delete→再作成で丸ごと上書きされるため、追加したコメント列はそのままでは消えてしまう。
そのため生成済みコメントは (日付, ユーザーID) をキーに本シートへ永続化し、
元データのハッシュが変わっていない限り、SOXAI_daily 再構築後に再スタンプ（Gemini再呼び出し無し）する。
"""

import hashlib
import logging
from datetime import UTC, datetime

import gspread

from src.config import COMMENT_LOG_SHEET

logger = logging.getLogger(__name__)

HEADERS = ["日付", "ユーザーID", "コメント", "データハッシュ", "生成日時"]


def compute_row_hash(row, target_metrics: list[str]) -> str:
    """当日の対象指標値から、変化検知用の短いハッシュを作る。"""
    parts = [f"{metric}={row.get(metric)}" for metric in target_metrics]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class CommentStore:
    def __init__(self, sh: gspread.Spreadsheet):
        self._sh = sh
        self._ws = self._get_or_create_ws()
        self._entries: dict[tuple[str, str], dict] = {}
        self._dirty = False
        self._load()

    def _get_or_create_ws(self):
        try:
            return self._sh.worksheet(COMMENT_LOG_SHEET)
        except gspread.WorksheetNotFound:
            ws = self._sh.add_worksheet(title=COMMENT_LOG_SHEET, rows=200, cols=len(HEADERS))
            ws.update("A1", [HEADERS])
            return ws

    def _load(self) -> None:
        for r in self._ws.get_all_records():
            key = (str(r.get("日付", "")), str(r.get("ユーザーID", "")))
            self._entries[key] = {
                "comment": r.get("コメント", ""),
                "hash": r.get("データハッシュ", ""),
                "generated_at": r.get("生成日時", ""),
            }

    def get(self, date_str: str, uid: str) -> dict | None:
        return self._entries.get((date_str, uid))

    def upsert(self, date_str: str, uid: str, comment: str, row_hash: str) -> None:
        self._entries[(date_str, uid)] = {
            "comment": comment,
            "hash": row_hash,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        self._dirty = True

    def flush(self) -> None:
        """変更があった場合のみ、ログシート全体を書き戻す。"""
        if not self._dirty:
            return
        rows = [HEADERS]
        for (date_str, uid), entry in sorted(self._entries.items()):
            rows.append([date_str, uid, entry["comment"], entry["hash"], entry["generated_at"]])
        # 日次で1行ずつ増え続けるため、初期グリッド(200行)を超えたら拡張する
        if len(rows) > self._ws.row_count:
            self._ws.resize(rows=len(rows) + 50)
        self._ws.clear()
        self._ws.update("A1", rows)
        self._dirty = False
