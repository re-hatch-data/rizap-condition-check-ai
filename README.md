# RIZAP コンディションチェックAIエージェント

被験者ごとの日次コンディションデータ（睡眠・ストレス・活動量）と前日アンケートから、
AIが**特徴的な値の指摘＋今日1日の過ごし方アドバイス**を自動生成し、
各被験者スプレッドシート内の `AIコメント_ログ` シートに書き込むバッチエージェント。

```
Cloud Scheduler(毎朝 JST 9:00 に起動。SOXAI Ring同期の完了実績が8:15〜8:40頃のため)
  ↓
Cloud Run Jobs(このリポジトリ、rizap-marketingプロジェクト)
  ├ soxai-runner サービスアカウントで Drive/Sheets/Gemini(Agent Platform) を認証
  ├ 被験者ごとの SOXAI_daily(日次サマリー)と フォームの回答 1(前日アンケート)を読み取り
  ├ 睡眠・ストレス・活動量について「施策開始前平均→開始後平均」の変化と、
  │   当日値の「開始後平均からのSD逸脱度」・欠測日数を計算
  ├ 変化のない日付はキャッシュを再利用、新規/変化ありの日付のみ Agent Platform（旧Vertex AI）経由でGeminiを呼び出し
  └ AIコメント_ログ シートに日付ごとのコメントを保存(無ければシートを作成、あれば追記・更新)
```

Geminiに渡すのは「実測値(睡眠時間・睡眠の内訳・就寝/起床時刻・ストレス・歩数・活動消費kcal)の
当日値・施策開始前平均・施策開始後平均・開始後平均からのSD逸脱度・欠測日数・前日アンケート回答」のみ。
QOLスコア等の意味を説明できない合成スコアや、過去30日の生データは渡さない
（詳細と理由は [docs/architecture.md](docs/architecture.md)）。

詳細な設計判断（なぜこの構成か）は [docs/architecture.md](docs/architecture.md) を参照。

## リポジトリ構成

```
src/
  main.py               # バッチ本体(全被験者のオーケストレーション)
  sheets_client.py       # Drive/Sheets API(被験者スプシ解決・SOXAI_daily/フォーム回答の読み取り)
  metrics.py             # 開始前平均・開始後平均・SD逸脱度・欠測日数の計算
  comment_generator.py   # Agent Platform（旧Vertex AI）経由でGeminiを呼び出しコメント生成
  comment_store.py       # AIコメント_ログシートへの保存(トレーナーが見る唯一の出力先)
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
認証は rizap-soxai-ring が使用中の soxai-runner サービスアカウントを再利用するため、
gcloudログイン済みなら以下の1コマンドで構築〜動作確認まで完了する:

```bash
./deploy/bootstrap.sh rizap-marketing
```

（対象フォルダIDは既定値としてコードに設定済み。SA名が異なる場合は `SA_EMAIL=...` で指定。
個別に実行する場合の手順は [docs/runbook.md](docs/runbook.md) を参照）

以降はCloud Schedulerが毎朝JST9:00（SOXAI Ring同期の完了後）に起動して実行する
（詳細は [docs/architecture.md](docs/architecture.md)）。

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
| `GOOGLE_CLOUD_LOCATION` | Agent Platform(旧Vertex AI・Gemini)のロケーション(既定 `us-central1`) |
| `COND_FOLDER_ID` | 被験者コンディションチェック親フォルダのDrive ID(既定は本番フォルダ) |
| `ROSTER_SHEET_ID` | マスター名簿(`00_被験者名簿`)のスプレッドシートID(既定は確定済みの本番ファイル) |
| `GOOGLE_APPLICATION_CREDENTIALS` | SAキーJSONのパス(本番はSecret Managerから自動マウント) |
| `GEMINI_MODEL` | Agent Platform(旧Vertex AI)経由で呼び出すGeminiモデルID |
| `SD_THRESHOLD` | フラグ検知の閾値(本人平均からの標準偏差、既定 `2.0`) |
| `COMMENT_MIN_LEN` / `COMMENT_MAX_LEN` | 生成コメントの目安文字数(既定 60〜120字) |
| `DRY_RUN` | `true`でSheetsへの書き込みをスキップ(動作確認用) |

## 運用上の注意

- 出力先の `AIコメント_ログ` シートは、既存の `rizap-soxai-ring`(毎朝JST7:00実行)が
  delete→再作成する対象(`SOXAI_daily`/`SOXAI_detail`)ではないため消えない。
  SOXAI_daily自体には書き込まない。
- 起動は毎朝JST9:00。SOXAI Ring同期はcron設定こそJST7:00だが、GitHub Actionsの
  スケジュール遅延で完了は8:15〜8:40頃(実測)のため、バッファを見て9:00にしている
  (`deploy/deploy.sh` の `SCHEDULE` で変更可能)。まれに同期が間に合わなかった日は
  翌朝の実行で前日分もまとめて生成される(欠落はしない)。
- コメントは日付ごとに保存され、元データ・アンケート回答に変化のない日付は
  Geminiを再呼び出ししない(コスト抑制)。
- アンケートは常に前日分を参照する(実行時刻には当日分が全員提出済みとは限らないため)。
- Drive/Sheets/Gemini(Agent Platform)の認証は soxai-runner サービスアカウントを再利用する
  (rizap-soxai-ring で対象シートへのアクセス実績あり)。キー失効時は runbook 参照。
