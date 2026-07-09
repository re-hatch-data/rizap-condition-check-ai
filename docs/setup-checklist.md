# セットアップ残タスク整理（2026-07-09時点）

## ⏱️ ネクスト

**ボール = RIZAP（新規GCPプロジェクトの払い出し）。これ待ち。**
REHATCH側の実装（本リポジトリ）は完了済み。

1. ⏳ RIZAPに新規GCPプロジェクトの払い出しを依頼 → 依頼文: `docs/iam-request.md`
2. ⏳ プロジェクトID確定後、`deploy/setup_gcp.sh` → OAuthトークン生成 → `deploy/deploy.sh`
   （手順は `docs/runbook.md` B節）
3. ⏸ デプロイ後、E2E動作確認（`scripts/preflight.py --ask` → 実シートへの反映確認）

## A. REHATCH側で今すぐできること（RIZAPからの返答を待たずに）

- [x] リポジトリ実装（`src/`一式・テスト・CI・deployスクリプト・ドキュメント）
- [x] `COND_FOLDER_ID` の確認（`rizap-soxai-ring/setup.sh` から確認済み）
- [ ] OAuthクライアント作成・`scripts/generate_oauth_token.py` の動作確認
      （GCPプロジェクトが無くても、個人のGCPプロジェクトで動作自体は確認可能）
- [ ] SD逸脱度の閾値（現在は初期値2SD）の妥当性を、実データのサンプルで確認

## B. GCPプロジェクト払い出し後の流れ

```
1. (RIZAP) 新規GCPプロジェクト作成・課金設定
2. (REHATCH) deploy/setup_gcp.sh 実行(API有効化・SA作成・IAM付与)
   → IAM付与が失敗する場合は (RIZAP) に依頼
3. (REHATCH) OAuthクライアント作成 → generate_oauth_token.py 実行(RIZAP側アカウントでログイン)
4. (REHATCH) preflight.py で疎通確認 → deploy.sh でデプロイ
5. (合同) 実シートでの動作確認 → 本番運用開始
```

## 運用開始前に決めること（PoC後でも可）

- [ ] 「適正値」の基準（個人内基準か、チーム/全体基準か、両方併用か）
- [ ] SD逸脱度の具体的な閾値の最終決定（`SD_THRESHOLD`環境変数で調整可能）
- [ ] Vertex AI経由のGeminiモデルの料金感の確認
