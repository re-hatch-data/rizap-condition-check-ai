# セットアップ残タスク整理（2026-07-10時点）

## ⏱️ ネクスト

**明日（7/11）のRIZAPミーティングで、既存プロジェクト `rizap-marketing` に構築する。**
新規プロジェクトの払い出しは不要になった。REHATCH側の実装（本リポジトリ）は完了済み。

1. ⏳ 事前準備: 正式なプロジェクトIDと、soxai-ring-runner サービスアカウントの
   正式なメールアドレスを確認（`docs/iam-request.md` の①〜③）
2. ⏳ ミーティング当日、Editor権限を持つ担当が `deploy/bootstrap.sh <PROJECT_ID>` を実行
   （手順: `docs/runbook.md` 冒頭。OAuth・ブラウザ認可は不要）
3. ⏸ 構築後、E2E動作確認（bootstrap末尾の即時実行 → 実シートへの反映確認 →
   翌朝以降、再スタンプが機能しているか数日目視）
4. ⏸ アンケート提出時刻の実態を確認し、必要なら `SCHEDULE` で起動時刻を調整

## A. REHATCH側で今すぐできること（RIZAPからの返答を待たずに）

- [x] リポジトリ実装（`src/`一式・テスト・CI・deployスクリプト・ドキュメント）
- [x] `COND_FOLDER_ID` の確認（`rizap-soxai-ring/setup.sh` から確認済み）
- [ ] OAuthクライアント作成・`scripts/generate_oauth_token.py` の動作確認
      （GCPプロジェクトが無くても、個人のGCPプロジェクトで動作自体は確認可能）
- [ ] SD逸脱度の閾値（現在は初期値2SD）の妥当性を、実データのサンプルで確認

## B. 構築当日の流れ

```
1. (RIZAP) 実行担当アカウントへ rizap-marketing のEditor権限付与、SA名の確認
2. (合同)  deploy/bootstrap.sh <PROJECT_ID> を実行
   - 内部で setup_gcp.sh(API有効化・IAM付与) → SAキーのSecret登録 → デプロイ
   - IAM付与が失敗する場合は (RIZAP) のIAM管理者に依頼
   - 最後に即時1回実行まで自動で行う
3. (合同) 実シートでの動作確認 → 本番運用開始
```

## 運用開始前に決めること（PoC後でも可）

- [ ] 「適正値」の基準（個人内基準か、チーム/全体基準か、両方併用か）
- [ ] SD逸脱度の具体的な閾値の最終決定（`SD_THRESHOLD`環境変数で調整可能）
- [ ] Vertex AI経由のGeminiモデルの料金感の確認
