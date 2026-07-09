"""環境変数ベースの設定。

- Cloud Run Jobs では実行サービスアカウントのADC（Application Default Credentials）を使う想定。
- ローカル開発ではリポジトリ直下の .env を自動で読み込む。
- 受領済みサービスアカウント JSON を使う場合は GOOGLE_APPLICATION_CREDENTIALS に
  キーファイルのパスを設定する（google-auth が自動で読み取る）。
"""

import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # 本番イメージに dotenv が無くても動作する
    pass


def _env(key: str, default: str = ""):
    return lambda: os.environ.get(key, default)


def _env_bool(key: str, default: bool = False):
    return lambda: os.environ.get(key, str(default)).strip().lower() in ("1", "true", "yes")


def _env_float(key: str, default: float):
    return lambda: float(os.environ.get(key, str(default)))


def _env_int(key: str, default: int):
    return lambda: int(os.environ.get(key, str(default)))


# 設計概要書で「特徴的な値」の対象として明記されている4指標。
# 拡張したい場合はここに列名（スプレッドシート上の日本語列名）を追加する。
TARGET_METRICS = ["QOLスコア", "活動スコア", "安静時代謝kcal", "活動消費kcal"]

DAILY_SHEET = "SOXAI_daily"
COMMENT_LOG_SHEET = "AIコメント_ログ"
COMMENT_COLUMN_HEADER = "コメント"
DATE_COLUMN = "日付"
UID_COLUMN = "ユーザーID"


@dataclass
class Settings:
    # --- Google Cloud ---
    gcp_project: str = field(default_factory=_env("GOOGLE_CLOUD_PROJECT"))
    gcp_location: str = field(default_factory=_env("GOOGLE_CLOUD_LOCATION", "us-east5"))

    # --- Google Drive / Sheets ---
    cond_folder_id: str = field(default_factory=_env("COND_FOLDER_ID"))

    # --- Claude (Vertex AI経由) ---
    claude_model: str = field(default_factory=_env("CLAUDE_MODEL", "claude-sonnet-4-5@20250929"))
    comment_min_len: int = field(default_factory=_env_int("COMMENT_MIN_LEN", 40))
    comment_max_len: int = field(default_factory=_env_int("COMMENT_MAX_LEN", 60))

    # --- フラグ検知 ---
    sd_threshold: float = field(default_factory=_env_float("SD_THRESHOLD", 2.0))
    history_days: int = field(default_factory=_env_int("HISTORY_DAYS", 30))

    dry_run: bool = field(default_factory=_env_bool("DRY_RUN", False))


settings = Settings()


def validate_settings(s: Settings | None = None) -> list[str]:
    """起動時チェック。不足している必須設定の一覧を返す。"""
    s = s or settings
    missing = []
    if not s.gcp_project:
        missing.append("GOOGLE_CLOUD_PROJECT")
    if not s.cond_folder_id:
        missing.append("COND_FOLDER_ID")
    return missing
