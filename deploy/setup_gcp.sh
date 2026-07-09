#!/usr/bin/env bash
# 初回のみ実行するGCPセットアップスクリプト(RIZAP側の新規プロジェクト向け)。
# 前提: gcloud CLIでログイン済み、対象プロジェクトにEditor権限あり。
#
# Usage: deploy/setup_gcp.sh <PROJECT_ID> [REGION]
set -euo pipefail

PROJECT_ID="${1:?Usage: setup_gcp.sh <PROJECT_ID> [REGION]}"
REGION="${2:-asia-northeast1}"
SA_NAME="condition-check-ai"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud config set project "${PROJECT_ID}"

echo "==> API有効化"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  cloudscheduler.googleapis.com \
  secretmanager.googleapis.com \
  aiplatform.googleapis.com

echo "==> サービスアカウント作成(Cloud Run Jobsの実行アイデンティティ)"
gcloud iam service-accounts create "${SA_NAME}" \
  --display-name="Condition Check AI (Cloud Run Jobs)" || echo "(既に存在します)"

echo "==> Vertex AI(Claude)呼び出し権限の付与"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/aiplatform.user" \
  --condition=None \
  || echo "!! roles/aiplatform.user の付与に失敗しました。IAM管理者に依頼してください。"

echo "==> Secret Manager にOAuthトークンの箱を作成(値は後で登録)"
gcloud secrets create oauth-token --replication-policy=automatic 2>/dev/null \
  || echo "(secret oauth-token は既に存在します)"

echo ""
echo "==> Drive/SheetsアクセスはRIZAP側アカウントのOAuthトークンで行う。"
echo "    ローカルで scripts/generate_oauth_token.py を実行してトークンを生成し、次で登録:"
echo "      gcloud secrets versions add oauth-token --data-file=credentials/oauth-token.json --project ${PROJECT_ID}"
echo ""

echo "==> Secret読み取り権限の付与"
gcloud secrets add-iam-policy-binding oauth-token \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor" \
  --condition=None \
  || echo "!! secretAccessor の付与に失敗しました。IAM管理者に依頼してください。"

echo "完了。次は deploy/deploy.sh を実行してください。"
