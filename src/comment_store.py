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
from src.rate_limit import with_rate_limit_retry

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
            return with_rate_limit_retry(self._sh.worksheet, COMMENT_LOG_SHEET)
        except gspread.WorksheetNotFound:
            ws = with_rate_limit_retry(
                self._sh.add_worksheet, title=COMMENT_LOG_SHEET, rows=200, cols=len(HEADERS)
            )
            with_rate_limit_retry(ws.update, "A1", [HEADERS])
            return ws

    def _load(self) -> None:
        records = with_rate_limit_retry(self._ws.get_all_records)
        # flush時に「以前より行数が減った」場合へ空行上書きで対応するため、既存の行数を覚えておく
        self._loaded_data_rows = len(records)
        for r in records:
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
        """変更があった場合のみ、ログシート全体を書き戻す。

        clear()→update()の2段階は使わない。clearが成功した直後にupdateが失敗
        (リトライ超過・タスクタイムアウト等)すると、トレーナーが見るログシートが
        空のまま残るため。update("A1", rows)の上書き1回で反映し、既存データより
        行数が減った場合(通常は起きない。読み込み時に重複キーが畳まれた場合など)は
        減った分を空行で上書きして古い内容を消す。"""
        if not self._dirty:
            return
        rows = [HEADERS]
        for (date_str, uid), entry in sorted(self._entries.items()):
            rows.append([date_str, entry["comment"], uid, entry["hash"], entry["generated_at"]])
        data_rows = len(rows) - 1
        stale_rows = getattr(self, "_loaded_data_rows", 0) - data_rows
        if stale_rows > 0:
            rows += [[""] * len(HEADERS)] * stale_rows
        # 日次で1行ずつ増え続けるため、初期グリッド(200行)を超えたら拡張する
        if len(rows) > self._ws.row_count:
            with_rate_limit_retry(self._ws.resize, rows=len(rows) + 50)
        with_rate_limit_retry(self._ws.update, "A1", rows)
        self._loaded_data_rows = data_rows
        self._dirty = False
