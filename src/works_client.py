"""LINE WORKS Botの疎通確認用クライアント（連携ミーティングで使用）。

認証はAPI 2.0のService Account(JWT)方式。LINE WORKS Developer Consoleで発行する
Client ID / Client Secret / Service Account / 秘密鍵と、Bot ID・送信先channelIdを
1つのJSONファイルにまとめて渡す。
本実装（毎朝のコメント生成ジョブへの組み込み）は、ミーティングでの要件確定後に行う。

設定JSONの形式:
{
  "client_id": "...",
  "client_secret": "...",
  "service_account": "...@...",
  "private_key": "-----BEGIN PRIVATE KEY-----\\n...",
  "bot_id": "...",
  "channel_id": "..."   ← 送信先トークルーム。scripts/works_setup.py create-channel で取得
}
"""

import json
import logging
import pathlib
import time
from dataclasses import dataclass

import jwt as pyjwt
import requests

logger = logging.getLogger(__name__)

AUTH_URL = "https://auth.worksmobile.com/oauth2/v2.0/token"
API_BASE = "https://www.worksapis.com/v1.0"

# LINE WORKSのテキストメッセージは1通あたり最大2,000文字
# (https://developers.worksmobile.com/jp/docs/bot-send-text)。余裕を見て分割する
MAX_TEXT_LEN = 1800

REQUIRED_KEYS = ("client_id", "client_secret", "service_account", "private_key", "bot_id")


@dataclass
class WorksBotConfig:
    client_id: str
    client_secret: str
    service_account: str
    private_key: str
    bot_id: str
    channel_id: str = ""


def load_works_config(path: str) -> WorksBotConfig | None:
    """設定JSONを読み込む。ファイルが無ければNone（=LINE WORKS連携は無効）。

    ファイルはあるのに必須キーが欠けている場合は、設定ミスに気付けるよう例外にする
    （黙って無効扱いにすると「登録したのに送られない」を調査しにくいため）。
    """
    p = pathlib.Path(path)
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED_KEYS if not data.get(k)]
    if missing:
        raise ValueError(f"LINE WORKS設定({path})に不足しているキーがあります: {', '.join(missing)}")
    return WorksBotConfig(
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        service_account=data["service_account"],
        private_key=data["private_key"],
        bot_id=str(data["bot_id"]),
        channel_id=str(data.get("channel_id", "")),
    )


def _split_text(text: str, limit: int = MAX_TEXT_LEN) -> list[str]:
    """文字数上限を超える場合に、行の切れ目でメッセージを分割する。"""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:  # 1行が上限を超える場合の保険
            chunks.append(line[:limit])
            line = line[limit:]
        if current and len(current) + 1 + len(line) > limit:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks


class WorksClient:
    def __init__(self, config: WorksBotConfig):
        self._config = config
        self._token: str | None = None

    def _build_assertion(self, now: int) -> str:
        # exp - iat は3600秒以内が仕様上限 (https://developers.worksmobile.com/jp/docs/auth-jwt)
        return pyjwt.encode(
            {
                "iss": self._config.client_id,
                "sub": self._config.service_account,
                "iat": now,
                "exp": now + 3600,
            },
            self._config.private_key,
            algorithm="RS256",
        )

    def _fetch_token(self) -> str:
        resp = requests.post(
            AUTH_URL,
            data={
                "assertion": self._build_assertion(int(time.time())),
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "client_id": self._config.client_id,
                "client_secret": self._config.client_secret,
                "scope": "bot",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def _headers(self) -> dict:
        if not self._token:
            self._token = self._fetch_token()
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    def send_text(self, text: str, channel_id: str | None = None) -> None:
        """トークルームへテキストを送る。上限超過分は複数メッセージに分割される。"""
        cid = channel_id or self._config.channel_id
        if not cid:
            raise ValueError(
                "channel_idが未設定です。scripts/works_setup.py create-channel でトークルームを作成し、"
                "返されたchannelIdを設定JSONに追記してください。"
            )
        for chunk in _split_text(text):
            resp = requests.post(
                f"{API_BASE}/bots/{self._config.bot_id}/channels/{cid}/messages",
                headers=self._headers(),
                json={"content": {"type": "text", "text": chunk}},
                timeout=30,
            )
            resp.raise_for_status()

    def create_channel(self, title: str, member_ids: list[str]) -> str:
        """Botをオーナーとするトークルームを作成し、channelIdを返す。

        member_ids はLINE WORKSのユーザーID（通常メールアドレス形式）。
        """
        resp = requests.post(
            f"{API_BASE}/bots/{self._config.bot_id}/channels",
            headers=self._headers(),
            json={"title": title, "members": member_ids},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["channelId"]
