"""Google Sheets/Drive APIのレート制限に対する簡易リトライ。

実測: 被験者23名分のスプレッドシートを逐次読み込むだけで、Sheets APIの
「1分あたりの読み取りリクエスト数」既定クォータ(60/分)を容易に超過し、
本番ジョブが毎回10〜14名分で失敗する事象が発生した。クォータ引き上げ申請が
完了するまでの当面の対策として、レート制限エラー発生時に指数バックオフで再試行する。

レート制限の現れ方は1つではない:
- Sheets API: 429 (RESOURCE_EXHAUSTED)
- Drive API: 403 + reason "rateLimitExceeded"/"userRateLimitExceeded" で返ることがある
- gspreadのopen_by_key等は403をPermissionErrorに変換して送出する(gspread 6.x)
いずれも取りこぼすと「リトライしたつもりが即死」になるため、この3系統をまとめて扱う。
"""

import logging
import time

from googleapiclient.errors import HttpError
from gspread.exceptions import APIError

logger = logging.getLogger(__name__)

_MAX_RETRIES = 6
_BASE_DELAY_SECONDS = 5

# 403応答のボディに含まれていたらレート制限とみなすreason(小文字で比較。
# "ratelimitexceeded"は"userRateLimitExceeded"にも部分一致する)
_RATE_LIMIT_MARKER = "ratelimitexceeded"


def _is_rate_limit(exc: Exception) -> bool:
    if isinstance(exc, APIError):
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
        if status == 429:
            return True
        if status == 403:
            body = getattr(response, "text", "") or ""
            return _RATE_LIMIT_MARKER in body.lower()
        return False
    if isinstance(exc, HttpError):
        if exc.resp.status == 429:
            return True
        if exc.resp.status == 403:
            body = exc.content.decode("utf-8", errors="ignore") if exc.content else ""
            return _RATE_LIMIT_MARKER in body.lower()
        return False
    return False


def with_rate_limit_retry(fn, *args, **kwargs):
    """fn(*args, **kwargs)を実行し、レート制限エラーの場合のみ指数バックオフで再試行する。
    レート制限以外の例外、または規定回数を使い切った場合はそのまま送出する。

    PermissionErrorも捕捉するのは、gspread 6.xが403をPermissionErrorに変換して
    送出するため(元のAPIErrorは__cause__に入っている)。レート制限起因でない
    PermissionError(共有漏れ等)はそのまま送出するので、名簿未共有時の
    フォールバック(sheets_client.load_training_start_dates)の挙動は変わらない。"""
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except (APIError, HttpError, PermissionError) as e:
            cause = e.__cause__ if isinstance(e, PermissionError) else e
            if not isinstance(cause, Exception) or not _is_rate_limit(cause) or attempt == _MAX_RETRIES:
                raise
            delay = _BASE_DELAY_SECONDS * (2**attempt)
            logger.warning(
                "Sheets/Drive APIのレート制限に達しました。%d秒待って再試行します(%d/%d回目)",
                delay,
                attempt + 1,
                _MAX_RETRIES,
            )
            time.sleep(delay)
