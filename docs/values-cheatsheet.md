# 値の対応表 ── どの値を・どこから取って・どこに入れるか

## 登場する値の一覧

| 値 | どこから取る | どこに入れる | 備考 |
|---|---|---|---|
| **PROJECT_ID** | RIZAP側で新規GCPプロジェクトを作成後に確定 | デプロイコマンドの引数 | 例: `rizap-condition-check` |
| **COND_FOLDER_ID** | 被験者コンディションチェック親フォルダのDrive URL | `.env` / デプロイ時の環境変数 | 既存の `rizap-soxai-ring` と共通の値 |
| **oauth-client.json** | RIZAP側GCPプロジェクトのコンソール →「認証情報」→ OAuthクライアントID作成（デスクトップアプリ） | ローカルの `credentials/oauth-client.json`（gitignore済み） | REHATCH側で作成可 |
| **oauth-token.json** | `scripts/generate_oauth_token.py` 実行時にRIZAP側アカウントでログイン・許可して生成 | Secret Manager `oauth-token` | ログイン情報はREHATCH側も把握しているため、RIZAP同席なしで実行可能 |
| **CLAUDE_MODEL** | Vertex AIのModel Gardenで提供されているClaudeモデルID | `.env` / デプロイ時の環境変数 | RIZAP側プロジェクトでの提供リージョン・有効化状況を要確認 |

**流れ**: RIZAPが新規GCPプロジェクトを作成 → PROJECT_ID確定 → `deploy/setup_gcp.sh` 実行 →
OAuthクライアント作成 → `scripts/generate_oauth_token.py` でトークン生成 → Secret Manager登録 →
`deploy/deploy.sh` でCloud Run Jobs + Cloud Scheduler設定

---

## ① OAuthクライアントの作成場所（GCPコンソール）

```
APIとサービス → 認証情報 → + 認証情報を作成 → OAuthクライアントID
  アプリケーションの種類: デスクトップアプリ
  → 作成後、JSONをダウンロードして credentials/oauth-client.json として配置
```

初回のみ、OAuth同意画面の設定（テストユーザーとしてRIZAP側の対象アカウントを追加、
もしくは社内限定公開）が必要な場合がある。

## ② トークン生成（ローカル、REHATCH側で実施可）

```bash
python -m scripts.generate_oauth_token
```

ブラウザが開くので、RIZAP側の対象Googleアカウントでログイン・許可する。
`credentials/oauth-token.json` が生成されるので、Secret Managerに登録する:

```bash
gcloud secrets create oauth-token --data-file=credentials/oauth-token.json --project <PROJECT_ID>
```

## ③ Cloud Run Jobsへの反映

`deploy/deploy.sh` が `/secrets/oauth-token.json` としてマウントする設定を含んでいるため、
Secret登録後にデプロイ（または再デプロイ）すれば自動的に反映される。
トークン自体を更新したい場合（再認可等）は:

```bash
gcloud secrets versions add oauth-token --data-file=credentials/oauth-token.json --project <PROJECT_ID>
```

（Cloud Run Jobsは実行のたびに`:latest`を読むため、再デプロイ不要）
