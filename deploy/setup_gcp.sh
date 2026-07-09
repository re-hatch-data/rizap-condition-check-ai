#!/usr/bin/env bash
# 初回のみ実行するGCPセットアップスクリプト(RIZAP側の既存プロジェクト rizap-marketing 向け)。
# 前提: gcloud CLIでログイン済み、対象プロジェクトにEditor権限あり。
#
# Drive/Sheetsアクセスは、既存パイプライン rizap-soxai-ring が使っている
# サービスアカウント(soxai-ring-runner)を再利用する。このSAは対象スプレッドシートへの
# アクセス実績が既にあるため、フォルダ共有やOAuth認可のやり直しが不要。
# 本エージェント用に追加で必要なのは Vertex AI(Gemini)呼び出し権限のみ。
#
# Usage: deploy/setup_gcp.sh <PROJECT_ID> [REGION]
# 環境変数(任意で上書き):
#   SA_EMAIL   利用するサービスアカウント(既定: soxai-ring-runner@<PROJECT_ID>...)
set -euo pipefail

PROJECT_ID="${1:?Usage: setup_gcp.sh <PROJECT_ID> [REGION]}"
REGION="${2:-asia-northeast1}"
SA_EMAIL="${SA_EMAIL:-soxai-ring-runner@${PROJECT_ID}.iam.gserviceaccount.com}"

gcloud config set project "${PROJECT_ID}"

echo "==> API有効化"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  cloudscheduler.googleapis.com \
  secretmanager.googleapis.com \
  aiplatform.googleapis.com

echo "==> サービスアカウントの確認: ${SA_EMAIL}"
if ! gcloud iam service-accounts describe "${SA_EMAIL}" >/dev/null 2>&1; then
  echo "!! ${SA_EMAIL} が見つかりません。"
  echo "   SA_EMAIL 環境変数で正しいサービスアカウントを指定して再実行してください。"
  echo "   (rizap-soxai-ring が使用しているSAの正式名はGCPコンソールのIAMで確認できます)"
  exit 1
fi

echo "==> Vertex AI(Gemini)呼び出し権限の付与"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/aiplatform.user" \
  --condition=None \
  || echo "!! roles/aiplatform.user の付与に失敗しました。IAM管理者に依頼してください。"

echo "==> Secret Manager にSAキーの箱を作成(値は bootstrap.sh が登録)"
gcloud secrets create soxai-sa-key --replication-policy=automatic 2>/dev/null \
  || echo "(secret soxai-sa-key は既に存在します)"

echo "==> Secret読み取り権限の付与"
gcloud secrets add-iam-policy-binding soxai-sa-key \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor" \
  --condition=None \
  || echo "!! secretAccessor の付与に失敗しました。IAM管理者に依頼してください。"

echo "完了。次は deploy/deploy.sh を実行してください。"
