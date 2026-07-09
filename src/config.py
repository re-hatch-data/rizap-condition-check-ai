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


# コメント対象の指標（SOXAI_daily上の列名）。
# トレーナー・本人がそのまま解釈して行動に繋げられる実測値のみを使う。
# QOLスコア・活動スコア・健康スコア・睡眠スコアなどの合成スコアは、値を見ても
# 「何が良い/悪いのか」を説明できずアドバイスに繋がらないため渡さない（2026-07-10決定）。
TARGET_METRICS = [
    "歩数",
    "活動消費kcal",
    "ストレス",
    "総睡眠min",
    "深睡眠min",
    "浅睡眠min",
    "REM_min",
    "入眠潜時min",
    "睡眠効率",
    "就寝時刻",
    "起床時刻",
]

# 睡眠が計測されていない日（総睡眠min=0）は、0ではなく欠測として扱う指標
SLEEP_METRICS = [
    "総睡眠min",
    "深睡眠min",
    "浅睡眠min",
    "REM_min",
    "入眠潜時min",
    "睡眠効率",
    "就寝時刻",
    "起床時刻",
]
TOTAL_SLEEP_COLUMN = "総睡眠min"

# ISO日時文字列 → 時刻(時間の小数)に変換して「普段より遅い/早い」を比較可能にする指標
TIME_METRICS = ["就寝時刻", "起床時刻"]

DAILY_SHEET = "SOXAI_daily"
COMMENT_LOG_SHEET = "AIコメント_ログ"
DATE_COLUMN = "日付"
UID_COLUMN = "ユーザーID"

# 当日アンケート（Googleフォーム）の回答シート。Q1体調・Q2業務負荷・Q3食事の予定・
# Q5困りごと等をプロンプトに含める（Q4 SOXAI RINGの同期状況は運用情報なので除外）。
FORM_SHEET = "フォームの回答 1"
FORM_TIMESTAMP_COLUMN = "タイムスタンプ"


@dataclass
class Settings:
    # --- Google Cloud ---
    gcp_project: str = field(default_factory=_env("GOOGLE_CLOUD_PROJECT"))
    gcp_location: str = field(default_factory=_env("GOOGLE_CLOUD_LOCATION", "us-central1"))

    # --- Google Drive / Sheets ---
    # 既定値は「コンディションチェック」親フォルダ（確定済み）。別環境で試す場合のみ上書きする。
    cond_folder_id: str = field(
        default_factory=_env("COND_FOLDER_ID", "1O7oYAdZ6opu_P9tZ-_0idO__E_WXKcGG")
    )

    # --- Gemini (Vertex AI経由) ---
    gemini_model: str = field(default_factory=_env("GEMINI_MODEL", "gemini-2.5-flash"))
    # 「特徴的な値の指摘＋今日1日の過ごし方アドバイス」を1〜2文で収める目安
    comment_min_len: int = field(default_factory=_env_int("COMMENT_MIN_LEN", 60))
    comment_max_len: int = field(default_factory=_env_int("COMMENT_MAX_LEN", 120))

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
