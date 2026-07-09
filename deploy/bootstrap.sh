#!/usr/bin/env bash
# ゼロから本番稼働までを1コマンドで行うラッパー(RIZAP側GCPプロジェクトでの初回構築用)。
# setup_gcp.sh → OAuthトークン生成/登録 → deploy.sh → 動作確認(即時1回実行) を順に実行する。
#
# 事前に必要なもの:
#   - gcloud CLI でログイン済み(対象プロジェクトのEditor権限を持つアカウント)
#   - python3 (3.12以上)
#   - GCPコンソールで作成したOAuthクライアント(デスクトップアプリ)のJSONを
#     credentials/oauth-client.json に配置(手順: docs/runbook.md)
#   - 環境変数 COND_FOLDER_ID(または .env に記載)
#
# Usage: deploy/bootstrap.sh <PROJECT_ID> [REGION]
set -euo pipefail

cd "$(dirname "$0")/.."
PROJECT_ID="${1:?Usage: bootstrap.sh <PROJECT_ID> [REGION]}"
REGION="${2:-asia-northeast1}"

# .env があれば読み込む(COND_FOLDER_ID など)
if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi
: "${COND_FOLDER_ID:?COND_FOLDER_ID を環境変数か .env で指定してください}"

echo "==> [1/5] GCP初期セットアップ(API有効化・サービスアカウント・IAM)"
./deploy/setup_gcp.sh "${PROJECT_ID}" "${REGION}"

echo "==> [2/5] Drive/Sheets用OAuthトークンの準備"
if [[ ! -f credentials/oauth-token.json ]]; then
  if [[ ! -f credentials/oauth-client.json ]]; then
    echo "!! credentials/oauth-client.json がありません。"
    echo "   GCPコンソール → APIとサービス → 認証情報 → OAuthクライアントID(デスクトップアプリ)を作成し、"
    echo "   JSONを credentials/oauth-client.json に置いてから再実行してください。"
    exit 1
  fi
  if [[ ! -d .venv ]]; then python3 -m venv .venv; fi
  ./.venv/bin/pip install -q -r requirements.txt
  # ブラウザが開くので、対象データにアクセスできるRIZAP側Googleアカウントでログイン・許可する
  ./.venv/bin/python -m scripts.generate_oauth_token
fi

echo "==> [3/5] トークンをSecret Managerへ登録"
gcloud secrets versions add oauth-token \
  --data-file=credentials/oauth-token.json --project "${PROJECT_ID}"

echo "==> [4/5] Cloud Run Jobs + Cloud Scheduler デプロイ"
COND_FOLDER_ID="${COND_FOLDER_ID}" REGION="${REGION}" ./deploy/deploy.sh "${PROJECT_ID}"

echo "==> [5/5] 動作確認(即時1回実行・完了まで待機)"
gcloud run jobs execute condition-check-ai \
  --project "${PROJECT_ID}" --region "${REGION}" --wait

echo ""
echo "✅ 構築完了。被験者スプレッドシートを開き、以下を確認してください:"
echo "   - SOXAI_daily のB列(日付の隣)にコメントが入っている"
echo "   - AIコメント_ログ シートが作成されている"
echo "   以降は毎朝JST8:30(SOXAI Ring同期の後)に自動実行されます。"
