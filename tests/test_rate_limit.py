from unittest.mock import Mock

import pytest
import requests
from googleapiclient.errors import HttpError
from gspread.exceptions import APIError

from src.rate_limit import with_rate_limit_retry


def _api_error(status_code: int, body: bytes = b"") -> APIError:
    response = requests.Response()
    response.status_code = status_code
    response._content = body
    return APIError(response)


def _http_error(status: int, content: bytes = b"error body") -> HttpError:
    resp = Mock()
    resp.status = status
    return HttpError(resp, content)


_DRIVE_RATE_LIMIT_BODY = (
    b'{"error": {"errors": [{"domain": "usageLimits", "reason": "userRateLimitExceeded"}],'
    b' "code": 403, "message": "User Rate Limit Exceeded"}}'
)


def test_returns_result_when_no_error():
    assert with_rate_limit_retry(lambda: 42) == 42


def test_retries_on_429_and_eventually_succeeds(monkeypatch):
    monkeypatch.setattr("src.rate_limit.time.sleep", lambda _: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _api_error(429)
        return "ok"

    assert with_rate_limit_retry(flaky) == "ok"
    assert calls["n"] == 3


def test_retries_on_429_for_http_error_too(monkeypatch):
    monkeypatch.setattr("src.rate_limit.time.sleep", lambda _: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise _http_error(429)
        return "ok"

    assert with_rate_limit_retry(flaky) == "ok"
    assert calls["n"] == 2


def test_does_not_retry_non_429_errors():
    calls = {"n": 0}

    def always_403():
        calls["n"] += 1
        raise _api_error(403)

    with pytest.raises(APIError):
        with_rate_limit_retry(always_403)
    assert calls["n"] == 1


def test_retries_403_with_rate_limit_reason(monkeypatch):
    """Drive APIはレート制限を429ではなく403+rateLimitExceededで返すことがある。"""
    monkeypatch.setattr("src.rate_limit.time.sleep", lambda _: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise _api_error(403, body=_DRIVE_RATE_LIMIT_BODY)
        return "ok"

    assert with_rate_limit_retry(flaky) == "ok"
    assert calls["n"] == 2


def test_retries_403_http_error_with_rate_limit_reason(monkeypatch):
    monkeypatch.setattr("src.rate_limit.time.sleep", lambda _: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise _http_error(403, content=_DRIVE_RATE_LIMIT_BODY)
        return "ok"

    assert with_rate_limit_retry(flaky) == "ok"
    assert calls["n"] == 2


def test_retries_permission_error_caused_by_rate_limit(monkeypatch):
    """gspread 6.xのopen_by_key等は403をPermissionErrorに変換する(元エラーは__cause__)。
    レート制限起因のものはリトライ対象にすること。"""
    monkeypatch.setattr("src.rate_limit.time.sleep", lambda _: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise PermissionError from _api_error(403, body=_DRIVE_RATE_LIMIT_BODY)
        return "ok"

    assert with_rate_limit_retry(flaky) == "ok"
    assert calls["n"] == 2


def test_does_not_retry_plain_permission_error():
    """共有漏れ等の純粋な権限エラーは即座に送出する（名簿未共有時の
    フォールバック挙動を変えないため）。"""
    calls = {"n": 0}

    def always_denied():
        calls["n"] += 1
        raise PermissionError from _api_error(403)

    with pytest.raises(PermissionError):
        with_rate_limit_retry(always_denied)
    assert calls["n"] == 1


def test_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr("src.rate_limit.time.sleep", lambda _: None)
    calls = {"n": 0}

    def always_429():
        calls["n"] += 1
        raise _api_error(429)

    with pytest.raises(APIError):
        with_rate_limit_retry(always_429)
    assert calls["n"] == 7  # 初回 + _MAX_RETRIES(6)
