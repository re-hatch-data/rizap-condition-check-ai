#!/usr/bin/env bash
# ゼロから本番稼働までを1コマンドで行うラッパー(RIZAP側プロジェクトでの初回構築用)。
# setup_gcp.sh → SAキーのSecret登録 → deploy.sh → 動作確認(即時1回実行) を順に実行する。
#
# 事前に必要なもの:
#   - gcloud CLI でログイン済み(対象プロジェクトのEditor権限を持つアカウント)
#   - 対象プロジェクトに soxai-runner サービスアカウントが存在すること
#     (名前が違う場合は SA_EMAIL 環境変数で指定)
#
# Usage: deploy/bootstrap.sh <PROJECT_ID>
#   例: deploy/bootstrap.sh rizap-marketing
#
# 実行スケジュールは毎朝JST9:00(SOXAI Ring同期の完了実績8:15〜8:40頃の後。
# 詳細はdeploy.shのコメント参照)。変更したい場合は SCHEDULE 環境変数で
# 上書きできる(cron式、Asia/Tokyo)。
# REGION は環境変数で上書き可(既定: asia-northeast1)。
set -euo pipefail

cd "$(dirname "$0")/.."
PROJECT_ID="${1:?Usage: bootstrap.sh <PROJECT_ID>}"
REGION="${REGION:-asia-northeast1}"
SA_EMAIL="${SA_EMAIL:-soxai-runner@${PROJECT_ID}.iam.gserviceaccount.com}"

echo "==> [1/4] GCP初期セットアップ(API有効化・IAM・Secretの箱)"
SA_EMAIL="${SA_EMAIL}" ./deploy/setup_gcp.sh "${PROJECT_ID}" "${REGION}"

echo "==> [2/4] SAキーの準備"
if gcloud secrets versions list condition-check-ai-sa-key --project "${PROJECT_ID}" \
    --filter="state=ENABLED" --format="value(name)" | grep -q .; then
  echo "(secret condition-check-ai-sa-key は登録済み。スキップします)"
else
  # 手元にキーJSONがあれば SA_KEY_FILE=path で指定。無ければその場で新規キーを発行する
  KEY_FILE="${SA_KEY_FILE:-}"
  CREATED_KEY=""
  if [[ -z "${KEY_FILE}" ]]; then
    KEY_FILE="$(mktemp)/sa-key.json"
    mkdir -p "$(dirname "${KEY_FILE}")"
    gcloud iam service-accounts keys create "${KEY_FILE}" \
      --iam-account "${SA_EMAIL}" --project "${PROJECT_ID}"
    CREATED_KEY=1
  fi
  gcloud secrets versions add condition-check-ai-sa-key --data-file="${KEY_FILE}" --project "${PROJECT_ID}"
  # Secret Manager登録後はローカルにキーを残さない
  if [[ -n "${CREATED_KEY}" ]]; then rm -f "${KEY_FILE}"; fi
fi

echo "==> [3/4] Cloud Run Jobs + Cloud Scheduler デプロイ(毎朝JST9:00)"
SA_EMAIL="${SA_EMAIL}" REGION="${REGION}" ./deploy/deploy.sh "${PROJECT_ID}"

echo "==> [4/4] 動作確認(即時1回実行・完了まで待機)"
gcloud run jobs execute condition-check-ai \
  --project "${PROJECT_ID}" --region "${REGION}" --wait

echo ""
echo "✅ 構築完了。被験者スプレッドシートを開き、以下を確認してください:"
echo "   - AIコメント_ログ シートが作成され、日付ごとのコメントが入っている"
echo "   以降は毎朝JST9:00(SOXAI Ring同期の完了後)に自動実行されます。"
