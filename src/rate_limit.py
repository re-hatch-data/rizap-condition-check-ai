"""Google Sheets/Drive APIの429(レート制限)に対する簡易リトライ。

実測: 被験者23名分のスプレッドシートを逐次読み込むだけで、Sheets APIの
「1分あたりの読み取りリクエスト数」既定クォータ(60/分)を容易に超過し、
本番ジョブが毎回10〜14名分で失敗する事象が発生した。クォータ引き上げ申請が
完了するまでの当面の対策として、429発生時に指数バックオフで再試行する。
"""

import logging
import time

from googleapiclient.errors import HttpError
from gspread.exceptions import APIError

logger = logging.getLogger(__name__)

_MAX_RETRIES = 6
_BASE_DELAY_SECONDS = 5


def _status_code(exc: Exception) -> int | None:
    if isinstance(exc, APIError):
        response = getattr(exc, "response", None)
        return getattr(response, "status_code", None)
    if isinstance(exc, HttpError):
        return exc.resp.status
    return None


def with_rate_limit_retry(fn, *args, **kwargs):
    """fn(*args, **kwargs)を実行し、429(レート制限)の場合のみ指数バックオフで再試行する。
    429以外の例外、または規定回数を使い切った場合はそのまま送出する。"""
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except (APIError, HttpError) as e:
            if _status_code(e) != 429 or attempt == _MAX_RETRIES:
                raise
            delay = _BASE_DELAY_SECONDS * (2**attempt)
            logger.warning(
                "Sheets/Drive APIのレート制限(429)に達しました。%d秒待って再試行します(%d/%d回目)",
                delay,
                attempt + 1,
                _MAX_RETRIES,
            )
            time.sleep(delay)
