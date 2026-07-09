# Runbook：ゼロから本番稼働まで

デプロイ先はRIZAP側の**既存GCPプロジェクト `rizap-marketing`**（BigQuery・既存分析エージェント
`rizap_data_analytics_aget` と同居。2026-07-10に新規プロジェクト払い出し方針から変更）。

## 当日の1コマンド構築（RIZAP担当者向け）

前提: gcloud CLIログイン済み（対象プロジェクトのEditor権限）、python3、
`credentials/oauth-client.json` 配置済み（下記B-3）。

```bash
git clone https://github.com/re-hatch-data/rizap-condition-check-ai.git
cd rizap-condition-check-ai
export COND_FOLDER_ID=<Google DriveのフォルダID>
./deploy/bootstrap.sh <PROJECT_ID>
```

途中でブラウザが1回開くので、対象データにアクセスできるRIZAP側Googleアカウントで
ログイン・許可する。最後に即時1回実行まで行い、シートへの反映を確認できる。

以下は個別に実行する場合の詳細手順。

## A. REHATCH側で今すぐ進められること（RIZAPからの返答を待たずに）

1. リポジトリをclone、ローカル環境を準備

   ```bash
   git clone <このリポジトリのURL>
   cd rizap-condition-check-ai
   python3 -m venv .venv && source .venv/bin/activate
   pip install -r requirements-dev.txt
   cp .env.example .env
   ```

2. `pytest` / `ruff check src tests scripts` が通ることを確認

3. RIZAP側へ `docs/iam-request.md` を送付（実行アカウントへのEditor権限付与などの事前依頼）

## B. 対象プロジェクトへのアクセスが整い次第

1. `.env` の `GOOGLE_CLOUD_PROJECT` / `COND_FOLDER_ID` を記入

2. 初回GCPセットアップ

   ```bash
   gcloud auth login
   ./deploy/setup_gcp.sh <PROJECT_ID>
   ```

   IAM付与で失敗した場合は `docs/iam-request.md` の内容をRIZAP側に依頼する。

3. OAuthクライアントを作成（GCPコンソール → APIとサービス → 認証情報 →
   OAuthクライアントID → デスクトップアプリ）→ JSONを `credentials/oauth-client.json` に配置。
   OAuth同意画面のユーザータイプは「内部」を選ぶ（Google Workspace内のアカウントで使う限り
   アプリ検証は不要）

4. OAuthトークンを生成（対象のRIZAP側Googleアカウントでログイン・許可）

   ```bash
   python -m scripts.generate_oauth_token
   gcloud secrets create oauth-token --data-file=credentials/oauth-token.json --project <PROJECT_ID>
   ```

5. 事前診断（権限・API有効化の確認）

   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS=  # 未設定でOK。OAuthトークンを優先的に使う
   python -m scripts.preflight
   python -m scripts.preflight --ask   # 被験者1名分のコメント生成までE2Eで確認
   ```

   NGが出た項目は `docs/iam-request.md` の該当箇所をRIZAP側に依頼する。

6. Cloud Run Jobs + Cloud Scheduler デプロイ

   ```bash
   export COND_FOLDER_ID=<Google DriveのフォルダID>
   ./deploy/deploy.sh <PROJECT_ID>
   ```

7. 即時1回実行して動作確認

   ```bash
   gcloud run jobs execute condition-check-ai --project <PROJECT_ID> --region asia-northeast1
   gcloud run jobs executions list --job condition-check-ai --project <PROJECT_ID> --region asia-northeast1
   ```

   対象スプレッドシートを開き、`SOXAI_daily` のB列にコメントが入っているか、
   `AIコメント_ログ` シートが作成されているかを確認する。

8. 本番運用開始：Cloud Schedulerが毎朝 JST 8:30（SOXAI Ring同期の後）に自動実行する。
   運用開始後しばらくは、翌朝もコメント列が正しく再構築されているか（上書き対策が
   機能しているか）を数日分は目視確認することを推奨。

## トラブルシュート

- **コメント列が翌朝消えている** → Cloud Schedulerの実行がSOXAI Ring同期より前になっていないか
  （`gcloud scheduler jobs describe condition-check-ai` でスケジュールを確認）
- **Vertex AI呼び出しが403** → `roles/aiplatform.user` の付与、およびVertex AI API
  （`aiplatform.googleapis.com`）が有効化されているか確認（`docs/iam-request.md` ③）
- **Drive/Sheetsアクセスが失敗する** → OAuthトークンの有効期限切れ・失効の可能性。
  `scripts/generate_oauth_token.py` を再実行し、`gcloud secrets versions add` で更新する
