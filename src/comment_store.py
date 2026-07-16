"""コメントの保存先（各被験者スプレッドシート内の `AIコメント_ログ`シート）。

トレーナーが見る唯一のアウトプット。SOXAI_daily には書き込まない
（既存パイプライン rizap-soxai-ring が毎朝 SOXAI_daily/SOXAI_detail を
delete→再作成しており、列を足しても消えるため。追加シートは削除対象外なので残る）。
シートが無ければ作成し、あれば (日付, ユーザーID) をキーに追記・更新する。
元データ・アンケートのハッシュが変わっていない日は再生成しない（Gemini呼び出しの節約）。
"""

import hashlib
import logging
from datetime import UTC, datetime

import gspread

from src.config import COMMENT_LOG_SHEET

logger = logging.getLogger(__name__)

# トレーナーが読む前提で、日付→コメントを先頭に置く
HEADERS = ["日付", "コメント", "ユーザーID", "データハッシュ", "生成日時"]


def compute_row_hash(row, target_metrics: list[str], extra: str = "") -> str:
    """当日の対象指標値（+アンケート回答などの追加入力）から、変化検知用の短いハッシュを作る。"""
    parts = [f"{metric}={row.get(metric)}" for metric in target_metrics]
    raw = "|".join(parts) + "|" + extra
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

    def has_date(self, date_str: str) -> bool:
        """指定日のコメントが（どのユーザーIDでも）保存済みかどうか。"""
        return any(date == date_str for date, _uid in self._entries)

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
            rows.append([date_str, entry["comment"], uid, entry["hash"], entry["generated_at"]])
        # 日次で1行ずつ増え続けるため、初期グリッド(200行)を超えたら拡張する
        if len(rows) > self._ws.row_count:
            self._ws.resize(rows=len(rows) + 50)
        self._ws.clear()
        self._ws.update("A1", rows)
        self._dirty = False
