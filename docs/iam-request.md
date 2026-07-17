# 必要な権限の整理（RIZAP側への依頼事項）

コンディションチェックAIエージェント（日次コメント自動生成）を、RIZAP様側の
`rizap-marketing` プロジェクトで動かすために必要な権限の一覧です。

## RIZAP側に事前にお願いすること

| # | 対象 | 内容 |
|---|------|------|
| ① | プロジェクト | 既存の `rizap-marketing`（BigQuery・既存分析エージェントが稼働中）を利用します。正式なプロジェクトIDをご共有ください（新規プロジェクトの払い出しは不要） |
| ② | セットアップ担当者（人間） | `deploy/bootstrap.sh` を実行する担当者に、プロジェクトの **編集者（Editor）** 権限を付与してください |
| ③ | サービスアカウント名の確認 | rizap-soxai-ring（毎朝のシート同期）が使用しているサービスアカウント（想定: `soxai-runner@...`）の正式なメールアドレスをご確認ください |

## セットアップスクリプトが自動で行う設定（参考）

`deploy/bootstrap.sh` 実行時に以下が設定されます。組織ポリシーで制限されている場合のみ
IAM管理者による手動付与をお願いする可能性があります。

| 対象 | 権限/設定 | 用途 |
|------|-----------|------|
| プロジェクト | API有効化: `run` / `cloudbuild` / `artifactregistry` / `cloudscheduler` / `secretmanager` / `aiplatform` | Cloud Run Jobs・ビルド・定期実行・SAキー保管・Gemini呼び出し |
| soxai-runner SA | `roles/aiplatform.user`（プロジェクト） | Agent Platform（旧Vertex AI）経由のGemini呼び出し |
| soxai-runner SA | `roles/run.invoker`（condition-check-ai ジョブ） | Cloud Schedulerからのジョブ起動 |
| soxai-runner SA | `roles/secretmanager.secretAccessor`（secret: condition-check-ai-sa-key） | 実行時にSAキーを読み込むため |
| Secret Manager | secret `condition-check-ai-sa-key` にSAキーJSONを登録 | Drive/Sheetsアクセス用の認証情報 |

## 追加対応が不要なもの

- **Driveフォルダの共有**: soxai-runner は rizap-soxai-ring で毎朝対象スプレッドシートを
  書き換えており、アクセス権が既にあるため追加の共有設定は不要です
- **OAuth認可（ブラウザログイン）**: サービスアカウント方式のため不要です
- **Geminiの利用規約同意**: Google純正モデルのため、Agent Platform(旧Vertex AI)のAPI有効化のみで利用できます

---

上記①〜③が整い次第、`deploy/bootstrap.sh <PROJECT_ID>` の1コマンドで構築が完了します
（詳細は `docs/runbook.md`）。
