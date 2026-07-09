# RIZAP コンディションチェックAIエージェント

被験者ごとの日次コンディションデータ（QOLスコア・活動スコア・安静時代謝kcal・活動消費kcalなど）から、
AIが**特徴的な値の指摘＋一言総評**を自動生成し、各被験者スプレッドシートのコメント列に書き込むバッチエージェント。

```
Cloud Scheduler(毎朝 JST 8:00)
  ↓
Cloud Run Jobs(このリポジトリ)
  ├ RIZAP側Googleアカウントの認可トークンでDrive/Sheets APIアクセス
  ├ 被験者ごとの SOXAI_daily を読み取り、前日比・7日平均比・SD逸脱度・欠測日数を計算
  ├ 変化のない日付はキャッシュを再利用、新規/変化ありの日付のみ Vertex AI経由でClaudeを呼び出し
  └ SOXAI_daily のB列(日付列の隣)にコメントを書き込み、元データ列は折りたたみ
```

詳細な設計判断（なぜこの構成か）は [docs/architecture.md](docs/architecture.md) を参照。

## リポジトリ構成

```
src/
  main.py               # バッチ本体(全被験者のオーケストレーション)
  sheets_client.py       # Drive/Sheets API(被験者スプシ解決・読み取り・コメント列書き込み)
  metrics.py             # 前日比・7日平均比・SD逸脱度・欠測日数の計算
  comment_generator.py   # Vertex AI経由でClaudeを呼び出しコメント生成
  comment_store.py       # AIコメント_ログシートへの永続キャッシュ
  config.py              # 環境変数設定
scripts/
  generate_oauth_token.py # RIZAP側アカウントでの初回OAuth認可(ローカルで1回実行)
  preflight.py             # 権限・API有効化・E2Eの事前診断ツール
deploy/
  setup_gcp.sh            # 初回GCPセットアップ(API有効化・SA作成・IAM付与)
  deploy.sh                # Cloud Run Jobs デプロイ + Cloud Scheduler設定
docs/
  architecture.md          # 設計判断の詳細
  runbook.md                # ゼロから本番稼働までの通し手順
  values-cheatsheet.md      # 値の対応表(どこから取ってどこに入れるか)
  iam-request.md             # RIZAP側へのセットアップ依頼文
  setup-checklist.md         # 残タスク管理
tests/                       # pytest(CI: .github/workflows/ci.yml)
```

## クイックスタート

```bash
git clone <このリポジトリのURL>
cd rizap-condition-check-ai
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # 値を記入(下記「環境変数」参照)
```

ゼロから本番稼働までの全手順は **[docs/runbook.md](docs/runbook.md)** に通しでまとめてある。

## セットアップ手順（全体フロー）

1. **RIZAP側に新規GCPプロジェクトの払い出しを依頼**（[docs/iam-request.md](docs/iam-request.md) を送付）

2. **GCP初期セットアップ**

   ```bash
   ./deploy/setup_gcp.sh <PROJECT_ID>
   ```

3. **OAuthクライアント作成 → トークン生成**（RIZAP側の対象Googleアカウントでログイン・許可）

   ```bash
   python -m scripts.generate_oauth_token
   gcloud secrets create oauth-token --data-file=credentials/oauth-token.json --project <PROJECT_ID>
   ```

4. **事前診断**

   ```bash
   python -m scripts.preflight
   python -m scripts.preflight --ask   # 被験者1名分のコメント生成までE2Eで確認
   ```

5. **Cloud Run Jobs + Cloud Scheduler デプロイ**

   ```bash
   export COND_FOLDER_ID=<Google DriveのフォルダID>
   ./deploy/deploy.sh <PROJECT_ID>
   ```

6. **動作確認**：即時1回実行し、対象スプレッドシートにコメント列が反映されるか確認

   ```bash
   gcloud run jobs execute condition-check-ai --project <PROJECT_ID> --region asia-northeast1
   ```

以降はCloud Schedulerが毎朝自動実行する（既存のSOXAI Ring同期の後にバッファを見てJST8:00起動）。

## ローカル開発

```bash
source .venv/bin/activate
set -a && source .env && set +a
python -m src.main            # DRY_RUN=true にしておけば書き込みなしで動作確認できる
```

### テスト・lint

```bash
pip install -r requirements-dev.txt
ruff check src tests scripts
pytest
```

push / PR時にGitHub Actionsでlint・テスト・Dockerビルドが自動実行される。

## 主要な環境変数

| 変数 | 説明 |
|------|------|
| `GOOGLE_CLOUD_PROJECT` | RIZAP側の新規GCPプロジェクトID |
| `GOOGLE_CLOUD_LOCATION` | Vertex AI(Claude)のロケーション(既定 `us-east5`。提供状況は要確認) |
| `COND_FOLDER_ID` | 被験者コンディションチェック親フォルダのDrive ID |
| `GOOGLE_OAUTH_TOKEN_FILE` | RIZAP側アカウントで認可したOAuthトークンファイルのパス |
| `CLAUDE_MODEL` | Vertex AI経由で呼び出すClaudeモデルID |
| `SD_THRESHOLD` | フラグ検知の閾値(本人平均からの標準偏差、既定 `2.0`) |
| `COMMENT_MIN_LEN` / `COMMENT_MAX_LEN` | 生成コメントの目安文字数(既定 40〜60字) |
| `DRY_RUN` | `true`でSheetsへの書き込みをスキップ(動作確認用) |

## 運用上の注意

- 既存の `rizap-soxai-ring`(GitHub Actions、毎朝JST7:00実行)が `SOXAI_daily` シートを
  毎回delete→再作成しているため、**本ジョブは必ずその後に実行する必要がある**
  (`deploy/deploy.sh` は既定でJST8:00にスケジュールする)。詳細は
  [docs/architecture.md](docs/architecture.md) を参照。
- コメントは `AIコメント_ログ` シートに永続キャッシュされ、元データに変化のない日付は
  Claudeを再呼び出ししない(コスト抑制)。
- Drive/Sheetsアクセスはサービスアカウント共有ではなく、RIZAP側アカウントのOAuth認可を使う。
  トークンが失効した場合は `scripts/generate_oauth_token.py` を再実行する。
