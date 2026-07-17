# 値の対応表 ── どの値を・どこから取って・どこに入れるか

## 登場する値の一覧

| 値 | 確定値 | どこに入れる | 備考 |
|---|---|---|---|
| **PROJECT_ID** | `rizap-marketing` | `deploy/bootstrap.sh` の引数 | 既存プロジェクト（BigQuery・既存分析エージェントと同居） |
| **SA_EMAIL** | `soxai-runner@rizap-marketing.iam.gserviceaccount.com` | スクリプトの既定値に設定済み | rizap-soxai-ring と同じSA。異なる場合のみ `SA_EMAIL=` で上書き |
| **COND_FOLDER_ID** | `1O7oYAdZ6opu_P9tZ-_0idO__E_WXKcGG` | コードの既定値に設定済み | コンディションチェック親フォルダ（Drive URLの `/folders/` 以降） |
| **ROSTER_SHEET_ID** | `1guzsxOVhRVIAMQpWXnbESOO6h6BqOk9tu4huHLd-_4U` | コードの既定値に設定済み | `00_被験者名簿`（シート名`被験者名簿`）。施策開始日の取得元。`soxai_id`列で各被験者と突き合わせる |
| **SAキーJSON** | bootstrap実行時に自動発行 | Secret Manager `condition-check-ai-sa-key` | 手元にキーがあれば `SA_KEY_FILE=` で指定可。ローカルには残さない |
| **GEMINI_MODEL** | `gemini-2.5-flash`（既定） | デプロイ時の環境変数 | Vertex AI経由。変更は `GEMINI_MODEL=` で |

**流れ**: gcloudログイン（Editor権限） → `deploy/bootstrap.sh rizap-marketing` →
内部で API有効化 → IAM付与 → SAキー発行・Secret登録 → Cloud Run Jobs + Scheduler設定 →
即時1回実行して `AIコメント_ログ` シートへの反映を確認

## SAキーの更新（失効・ローテーション時）

```bash
gcloud iam service-accounts keys create /tmp/sa-key.json \
  --iam-account soxai-runner@rizap-marketing.iam.gserviceaccount.com
gcloud secrets versions add condition-check-ai-sa-key --data-file=/tmp/sa-key.json --project rizap-marketing
rm /tmp/sa-key.json
```

（Cloud Run Jobsは実行のたびに `:latest` を読むため、再デプロイ不要）

## （参考）OAuthフォールバック

ローカル検証でSAキーを使いたくない場合のみ、`scripts/generate_oauth_token.py` で
OAuthトークンを生成し `GOOGLE_OAUTH_TOKEN_FILE` に指定する。本番では使わない。
