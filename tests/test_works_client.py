import json

import pytest

from src.works_client import MAX_TEXT_LEN, _split_text, load_works_config


def _valid_config() -> dict:
    return {
        "client_id": "cid",
        "client_secret": "secret",
        "service_account": "bot@example.serviceaccount",
        "private_key": "-----BEGIN PRIVATE KEY-----\n...",
        "bot_id": "12345",
        "channel_id": "ch-1",
    }


def test_load_works_config_returns_none_when_file_missing(tmp_path):
    assert load_works_config(str(tmp_path / "works-bot.json")) is None


def test_load_works_config_parses_valid_file(tmp_path):
    path = tmp_path / "works-bot.json"
    path.write_text(json.dumps(_valid_config()), encoding="utf-8")

    config = load_works_config(str(path))

    assert config is not None
    assert config.bot_id == "12345"
    assert config.channel_id == "ch-1"


def test_load_works_config_raises_on_missing_key(tmp_path):
    """ファイルはあるのにキーが欠けている場合は、黙って無効化せずエラーにする。"""
    data = _valid_config()
    del data["bot_id"]
    path = tmp_path / "works-bot.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="bot_id"):
        load_works_config(str(path))


def test_split_text_keeps_short_text_as_single_message():
    assert _split_text("こんにちは") == ["こんにちは"]


def test_split_text_splits_on_line_boundaries():
    """LINE WORKSの2,000字上限を超える本文は、行の切れ目で複数メッセージに分割する。"""
    line = "あ" * 800
    text = "\n".join([line, line, line])  # 2,402文字 → 2通(1,601字+800字)に分割される

    chunks = _split_text(text)

    assert len(chunks) == 2
    assert all(len(c) <= MAX_TEXT_LEN for c in chunks)
    assert "\n".join(chunks).replace("\n", "") == text.replace("\n", "")
