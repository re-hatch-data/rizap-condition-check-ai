# RIZAP コンディションチェックAIエージェント

被験者ごとの日次コンディションデータ（QOLスコア・活動スコア・安静時代謝kcal・活動消費kcalなど）から、
AIが**特徴的な値の指摘＋一言総評**を自動生成し、各被験者スプレッドシートのコメント列に書き込むバッチエージェント。

```
Cloud Scheduler(毎朝 JST 8:30)
  ↓
Cloud Run Jobs(このリポジトリ、rizap-marketingプロジェクト)
  ├ soxai-ring-runner サービスアカウントで Drive/Sheets/Vertex AI を認証
  ├ 被験者ごとの SOXAI_daily(日次サマリー)と フォームの回答 1(当日アンケート)を読み取り
  ├ 前日比・7日平均比・本人平均からのSD逸脱度・欠測日数を計算
  ├ 変化のない日付はキャッシュを再利用、新規/変化ありの日付のみ Vertex AI経由でGeminiを呼び出し
  └ SOXAI_daily のB列(日付列の隣)にコメントを書き込み、元データ列は折りたたみ
```

Geminiに渡すのは「当日値・前日比・7日平均比・本人平均からのSD逸脱度・欠測日数・
当日アンケート回答」のみ。過去30日の生データは渡さない（当日のコンディション評価が
過去の値に引っ張られるのを防ぐため。詳細は [docs/architecture.md](docs/architecture.md)）。

詳細な設計判断（なぜこの構成か）は [docs/architecture.md](docs/architecture.md) を参照。

## リポジトリ構成

```
src/
  main.py               # バッチ本体(全被験者のオーケストレーション)
  sheets_client.py       # Drive/Sheets API(被験者スプシ解決・読み取り・コメント列書き込み)
  metrics.py             # 前日比・7日平均比・SD逸脱度・欠測日数の計算
  comment_generator.py   # Vertex AI経由でGeminiを呼び出しコメント生成
  comment_store.py       # AIコメント_ログシートへの永続キャッシュ
  config.py              # 環境変数設定
scripts/
  generate_oauth_token.py # OAuth認可(ローカル検証用のフォールバック。本番では未使用)
  preflight.py             # 権限・API有効化・E2Eの事前診断ツール
deploy/
  bootstrap.sh            # ↓2つ+SAキー登録+動作確認を通しで行う1コマンド構築
  setup_gcp.sh            # 初回GCPセットアップ(API有効化・IAM付与)
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

デプロイ先はRIZAP側の既存GCPプロジェクト（`rizap-marketing`。BigQuery・既存分析エージェントと同居）。
認証は rizap-soxai-ring が使用中の soxai-ring-runner サービスアカウントを再利用するため、
gcloudログイン済みなら以下の1コマンドで構築〜動作確認まで完了する:

```bash
./deploy/bootstrap.sh <PROJECT_ID>
```

（対象フォルダIDは既定値としてコードに設定済み。SA名が異なる場合は `SA_EMAIL=...` で指定。
個別に実行する場合の手順は [docs/runbook.md](docs/runbook.md) を参照）

以降はCloud Schedulerが毎朝自動実行する（既存のSOXAI Ring同期の後にバッファを見てJST8:30起動）。

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
| `GOOGLE_CLOUD_PROJECT` | RIZAP側のGCPプロジェクトID（`rizap-marketing`） |
| `GOOGLE_CLOUD_LOCATION` | Vertex AI(Gemini)のロケーション(既定 `us-central1`) |
| `COND_FOLDER_ID` | 被験者コンディションチェック親フォルダのDrive ID(既定は本番フォルダ) |
| `GOOGLE_APPLICATION_CREDENTIALS` | SAキーJSONのパス(本番はSecret Managerから自動マウント) |
| `GEMINI_MODEL` | Vertex AI経由で呼び出すGeminiモデルID |
| `SD_THRESHOLD` | フラグ検知の閾値(本人平均からの標準偏差、既定 `2.0`) |
| `COMMENT_MIN_LEN` / `COMMENT_MAX_LEN` | 生成コメントの目安文字数(既定 40〜60字) |
| `DRY_RUN` | `true`でSheetsへの書き込みをスキップ(動作確認用) |

## 運用上の注意

- 既存の `rizap-soxai-ring`(GitHub Actions、毎朝JST7:00実行)が `SOXAI_daily` シートを
  毎回delete→再作成しているため、**本ジョブは必ずその後に実行する必要がある**
  (`deploy/deploy.sh` は既定でJST8:30にスケジュールする。GitHub Actionsのcron遅延も考慮)。詳細は
  [docs/architecture.md](docs/architecture.md) を参照。
- コメントは `AIコメント_ログ` シートに永続キャッシュされ、元データ・アンケート回答に
  変化のない日付はGeminiを再呼び出ししない(コスト抑制)。
- 当日アンケートがジョブ実行(8:30)より後に提出された場合、その日のコメントには
  反映されないが、翌朝の実行で自動的に再生成・反映される。
- Drive/Sheets/Vertex AIの認証は soxai-ring-runner サービスアカウントを再利用する
  (rizap-soxai-ring で対象シートへのアクセス実績あり)。キー失効時は runbook 参照。
