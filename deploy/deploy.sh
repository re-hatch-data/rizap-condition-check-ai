#!/usr/bin/env bash
# Cloud Run Jobsへのデプロイ + Cloud Schedulerでの毎朝起動設定。
#
# 毎朝JST9:00に1回起動する。
# 時刻の根拠: 既存パイプライン rizap-soxai-ring(GitHub Actions, cron設定はJST7:00)は、
# GitHub Actions側のスケジュール遅延で実際の開始は7時台後半、完了は8:15〜8:40頃
# (直近10回の実測)。9:00ならバッファを持って同期完了後に実行できる。
#
# ジョブ自体は「日付ごとに、生成済みで変化が無ければスキップ・新規/変化ありのみ生成」
# という冪等な作りのため、同期がまれに9:00に間に合わなかった日はその日の生成は行われず、
# 翌朝の実行で前日分もまとめて生成される(欠落はしない)。同期の遅延が常態化した場合は
# SCHEDULE環境変数で時刻を後ろへずらすだけでよい。
#
# Usage: deploy/deploy.sh <PROJECT_ID>
#
# 環境変数(任意で上書き):
#   SA_EMAIL   実行サービスアカウント(既定: soxai-runner@<PROJECT_ID>...)
#   REGION     Cloud Runのリージョン(既定: asia-northeast1)
#   SCHEDULE   Cloud Schedulerのcron式(既定: "0 9 * * *" = 毎朝JST9:00)
set -euo pipefail

PROJECT_ID="${1:?Usage: deploy.sh <PROJECT_ID>}"
REGION="${REGION:-asia-northeast1}"
SCHEDULE="${SCHEDULE:-0 9 * * *}"
JOB_NAME="condition-check-ai"
SA_EMAIL="${SA_EMAIL:-soxai-runner@${PROJECT_ID}.iam.gserviceaccount.com}"

ENV_VARS="GOOGLE_CLOUD_PROJECT=${PROJECT_ID}"
# us-central1 = Gemini(Vertex AI)の利用リージョン(config.py の既定と揃える)
ENV_VARS="${ENV_VARS},GOOGLE_CLOUD_LOCATION=${VERTEX_LOCATION:-us-central1}"
ENV_VARS="${ENV_VARS},COND_FOLDER_ID=${COND_FOLDER_ID:-1O7oYAdZ6opu_P9tZ-_0idO__E_WXKcGG}"
ENV_VARS="${ENV_VARS},GEMINI_MODEL=${GEMINI_MODEL:-gemini-2.5-flash}"
# Drive/Sheets/Vertex AIすべて soxai-runner のSAキー(ADC)で認証する
ENV_VARS="${ENV_VARS},GOOGLE_APPLICATION_CREDENTIALS=/secrets/sa-key.json"

echo "==> Cloud Run Jobs デプロイ"
gcloud run jobs deploy "${JOB_NAME}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --source . \
  --service-account "${SA_EMAIL}" \
  --memory 512Mi \
  --max-retries 1 \
  --task-timeout 30m \
  --set-env-vars "${ENV_VARS}" \
  --set-secrets "/secrets/sa-key.json=condition-check-ai-sa-key:latest"

echo "==> Cloud Schedulerで実行権限を付与(自分自身をトリガー)"
gcloud run jobs add-iam-policy-binding "${JOB_NAME}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.invoker" \
  --condition=None \
  || echo "!! run.invoker の付与に失敗しました。IAM管理者に依頼してください。"

echo "==> Cloud Scheduler ジョブ作成/更新(毎朝 ${SCHEDULE} JST)"
SCHEDULER_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run"
if gcloud scheduler jobs describe "${JOB_NAME}" --project "${PROJECT_ID}" --location "${REGION}" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "${JOB_NAME}" \
    --project "${PROJECT_ID}" --location "${REGION}" \
    --schedule="${SCHEDULE}" --time-zone="Asia/Tokyo" \
    --uri="${SCHEDULER_URI}" --http-method=POST \
    --oauth-service-account-email="${SA_EMAIL}"
else
  gcloud scheduler jobs create http "${JOB_NAME}" \
    --project "${PROJECT_ID}" --location "${REGION}" \
    --schedule="${SCHEDULE}" --time-zone="Asia/Tokyo" \
    --uri="${SCHEDULER_URI}" --http-method=POST \
    --oauth-service-account-email="${SA_EMAIL}"
fi

echo ""
echo "============================================================"
echo "✅ デプロイ完了"
echo ""
echo "  Cloud Run Job : ${JOB_NAME}（${REGION}）"
echo "  起動スケジュール: ${SCHEDULE}（Asia/Tokyo）"
echo ""
echo "  動作確認（即時1回実行）:"
echo "    gcloud run jobs execute ${JOB_NAME} --project ${PROJECT_ID} --region ${REGION}"
echo "============================================================"
