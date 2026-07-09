# Runbook：ゼロから本番稼働まで

デプロイ先はRIZAP側の**既存GCPプロジェクト `rizap-marketing`**（BigQuery・既存分析エージェント
`rizap_data_analytics_aget` と同居。2026-07-10に新規プロジェクト払い出し方針から変更）。
認証は rizap-soxai-ring が使用中の **soxai-runner サービスアカウントを再利用**する
（対象スプレッドシートへのアクセス実績が既にあるため、共有設定もOAuth認可も不要）。

## 当日の1コマンド構築（RIZAP担当者向け）

前提: gcloud CLIログイン済み（対象プロジェクトのEditor権限）。それだけ。

```bash
git clone https://github.com/re-hatch-data/rizap-condition-check-ai.git
cd rizap-condition-check-ai
./deploy/bootstrap.sh <PROJECT_ID>
```

これで API有効化 → IAM付与 → SAキーのSecret登録 → Cloud Run Jobs + Schedulerデプロイ →
即時1回実行（シート反映の確認）まで通しで完了する。

- 対象フォルダIDは既定値としてコード側に設定済み（変える場合は `COND_FOLDER_ID` 環境変数）
- SAの名前が `soxai-runner@<PROJECT_ID>.iam.gserviceaccount.com` と異なる場合は
  `SA_EMAIL=<正式なSAメール> ./deploy/bootstrap.sh <PROJECT_ID>` で指定
- 手元に既存のSAキーJSONがある場合は `SA_KEY_FILE=<パス>` で渡せる（無ければ新規キーを発行し、
  Secret Manager登録後にローカルからは削除する）

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

3. RIZAP側へ `docs/iam-request.md` を送付（Editor権限付与・SA名の確認などの事前依頼）

## B. 対象プロジェクトへのアクセスが整い次第（個別実行する場合）

1. 初回GCPセットアップ（API有効化・IAM付与・Secretの箱作成）

   ```bash
   gcloud auth login
   ./deploy/setup_gcp.sh <PROJECT_ID>
   ```

   IAM付与で失敗した場合は `docs/iam-request.md` の権限一覧をRIZAP側に依頼する。

2. SAキーをSecret Managerに登録

   ```bash
   gcloud iam service-accounts keys create /tmp/sa-key.json \
     --iam-account soxai-runner@<PROJECT_ID>.iam.gserviceaccount.com
   gcloud secrets versions add soxai-sa-key --data-file=/tmp/sa-key.json
   rm /tmp/sa-key.json
   ```

3. 事前診断（権限・API有効化の確認。ローカルで実行する場合）

   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS=<SAキーJSONのパス>
   python -m scripts.preflight
   python -m scripts.preflight --ask   # 被験者1名分のコメント生成までE2Eで確認
   ```

4. Cloud Run Jobs + Cloud Scheduler デプロイ

   ```bash
   ./deploy/deploy.sh <PROJECT_ID>
   ```

5. 即時1回実行して動作確認

   ```bash
   gcloud run jobs execute condition-check-ai --project <PROJECT_ID> --region asia-northeast1 --wait
   ```

   対象スプレッドシートを開き、`AIコメント_ログ` シートが作成され、
   日付ごとのコメントが入っているかを確認する（SOXAI_daily自体には書き込まない）。

6. 本番運用開始：Cloud Schedulerが毎朝 JST 8:30（SOXAI Ring同期の後）に自動実行する。
   運用開始後しばらくは、当日分のコメントが毎朝追記されているかを数日分は目視確認することを推奨。
   当日アンケートの提出が8:30より遅い被験者が多い場合は、`SCHEDULE` 環境変数で
   起動時刻を遅らせて再デプロイする（例: `SCHEDULE="30 9 * * *" ./deploy/deploy.sh <PROJECT_ID>`）。

## トラブルシュート

- **当日分のコメントが生成されない/前日までしか無い** → Cloud Schedulerの実行が
  SOXAI Ring同期(JST7:00)より前になっていないか
  （`gcloud scheduler jobs describe condition-check-ai` でスケジュールを確認）
- **Vertex AI呼び出しが403** → `roles/aiplatform.user` の付与、およびVertex AI API
  （`aiplatform.googleapis.com`）が有効化されているか確認（`docs/iam-request.md` 参照）
- **Drive/Sheetsアクセスが403/404** → soxai-runner に対象フォルダのアクセス権があるか
  （rizap-soxai-ring の同期が正常に動いていれば権限はあるはず）、SAキーが失効していないかを確認。
  キーを再発行する場合: `gcloud iam service-accounts keys create ...` →
  `gcloud secrets versions add soxai-sa-key --data-file=...`
- **アンケートがコメントに反映されない** → 提出時刻がジョブ実行(8:30)より後の可能性。
  翌朝の実行で自動的に再生成・反映される
