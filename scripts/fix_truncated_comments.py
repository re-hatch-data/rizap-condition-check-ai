"""途中で切れているAIコメントを検出し、再生成されるようデータハッシュをクリアする。

max_output_tokens予算をthinkingトークンが消費してしまい、コメント本文が
途中で打ち切られていたバグ(src/comment_generator.py修正済み)の影響を受けた
既存ログ行をクリアするための一回限りの後始末スクリプト。
実際の削除は行わず、対象行の「データハッシュ」を空にするだけなので、
次回のバッチ実行時にその行だけが再生成される。
"""

import sys
import time

from gspread.utils import rowcol_to_a1

from src.comment_store import COMMENT_LOG_SHEET
from src.config import settings
from src.sheets_client import get_google_services, list_subject_spreadsheets

SENTENCE_END = ("。", "！", "？", "」", "…")


def looks_truncated(comment: str) -> bool:
    c = comment.strip()
    if not c:
        return False
    return not c.endswith(SENTENCE_END)


def main() -> int:
    drive_svc, _sheets_svc, gc = get_google_services()
    subjects = list_subject_spreadsheets(drive_svc, settings.cond_folder_id)
    print(f"対象被験者数: {len(subjects)}")

    total_flagged = 0
    for subject in subjects:
        name = subject["folder_name"]
        time.sleep(3)  # 被験者間に間隔を空けて読み取りレートも抑える
        sh = gc.open_by_key(subject["spreadsheet_id"])
        try:
            ws = sh.worksheet(COMMENT_LOG_SHEET)
        except Exception:
            print(f"  [{name}] {COMMENT_LOG_SHEET} シートなし。スキップ")
            continue

        values = ws.get_all_values()  # 1回のAPI呼び出しでヘッダー+データを取得
        header = values[0]
        hash_col = header.index("データハッシュ") + 1
        comment_col = header.index("コメント")
        date_col = header.index("日付")

        flagged = []
        for i, row in enumerate(values[1:], start=2):  # 1行目はヘッダー
            comment = row[comment_col] if len(row) > comment_col else ""
            date_str = row[date_col] if len(row) > date_col else ""
            if looks_truncated(comment):
                flagged.append((i, date_str, comment))

        if not flagged:
            print(f"  [{name}] 途切れコメントなし")
            continue

        print(f"  [{name}] 途切れ検出 {len(flagged)}件")
        # 1被験者につきAPI呼び出し1回にまとめてレート制限を回避する
        body = [
            {"range": rowcol_to_a1(row_i, hash_col), "values": [[""]]}
            for row_i, _date_str, _comment in flagged
        ]
        ws.batch_update(body)
        total_flagged += len(flagged)
        time.sleep(2)  # 被験者間に間隔を空けて書き込みレートを抑える

    print(f"\n合計 {total_flagged}件のデータハッシュをクリアしました。"
          "次回のジョブ実行でこれらの日付のみ再生成されます。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
