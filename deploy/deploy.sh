#!/usr/bin/env bash
# Cloud Run Jobsへのデプロイ + Cloud Schedulerでの毎朝繰り返し起動設定。
#
# 固定時刻に1回だけ起動するのではなく、JST7:00〜8:55の間、5分おきに起動する。
# ジョブ自体は「その日のデータがまだ無ければ数秒で終了、生成済みなら数秒で終了、
# 新規に揃っていれば生成」という冪等な作りなので、空振りの実行はごく低コストで、
# 待機ロジック(sleep等)をコード側に書く必要がない。
#
# こうする理由: 既存パイプライン rizap-soxai-ring(GitHub Actions, 毎朝JST7:00実行・
# タイムアウト上限55分)は、GitHub Actions側のスケジュール実行が混雑時に数十分遅れる
# ことがあり、完了時刻を固定では読めない。5分おきに確認することで、
# 「できるだけ早く(早ければ7:05〜10分で検知)」と「リスクをほぼ0にする(最大8:55まで
# 確認し続ける＝旧来のJST8:30固定より広い安全域)」を両立する。
# 1日の途中で当日分の生成が完了した後の空振り実行も、キャッシュ判定のみで即終了するため
# 実質無視できるコストしかかからない。
#
# Usage: deploy/deploy.sh <PROJECT_ID>
#
# 環境変数(任意で上書き):
#   SA_EMAIL   実行サービスアカウント(既定: soxai-runner@<PROJECT_ID>...)
#   REGION     Cloud Runのリージョン(既定: asia-northeast1)
#   SCHEDULE   Cloud Schedulerのcron式(既定: "*/5 7,8 * * *" = JST7:00〜8:55の5分おき)
set -euo pipefail

PROJECT_ID="${1:?Usage: deploy.sh <PROJECT_ID>}"
REGION="${REGION:-asia-northeast1}"
SCHEDULE="${SCHEDULE:-*/5 7,8 * * *}"
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
  --set-secrets "/secrets/sa-key.json=soxai-sa-key:latest"

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
