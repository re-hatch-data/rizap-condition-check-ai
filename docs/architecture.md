# アーキテクチャ

```
Cloud Scheduler(毎朝 JST 8:30 ── SOXAI Ring同期(JST7:00/最大55分・GitHub Actionsのcron遅延あり)の後にバッファを見て起動)
  ↓ HTTP(jobs.run)
Cloud Run Jobs(このリポジトリ)
  ├ RIZAP側Googleアカウントのトークンで Drive/Sheets API 認証(OAuth・SA共有なし)
  ├ COND_FOLDER_ID配下の被験者フォルダを走査 → 各「コンディションチェック」スプレッドシートを解決
  ├ 各スプレッドシートの SOXAI_daily を読み取り
  ├ 前日比・7日平均比・本人平均からのSD逸脱度・欠測日数を計算 → 閾値超えをフラグ化
  ├ AIコメント_ログ(このジョブが管理する永続シート)と突き合わせ、
  │   変化のない日付はキャッシュを再利用、新規/変化ありの日付のみ Vertex AI経由でGeminiを呼び出し
  ├ SOXAI_daily の B列(日付列の隣)にコメント列を書き込み、元データ列は折りたたみ
  └ AIコメント_ログを更新
```

## なぜこの構成か

### なぜ「コメントの永続キャッシュ + 再スタンプ」方式か
既存の `rizap-soxai-ring`(GitHub Actions、毎朝JST7:00実行)が `SOXAI_daily` シートを
**毎回delete→再作成**しているため、単純にコメント列を追加するだけでは翌朝の同期で消える。
このジョブは常にSOXAI Ring同期の後に実行し、消えたコメント列を再構築する前提で設計している。
過去日付のコメントはキャッシュ(`AIコメント_ログ`)から再利用するため、Gemini呼び出しは
新規・変化があった日付分のみで済む(コスト・レイテンシを抑制)。

### なぜCloud Run Jobs(常駐サービスではない)か
Slack Botのような常時起点のリクエストを受けるサービスではなく、日次バッチのため、
HTTPエンドポイント・認証設定が不要なJobs形式の方がシンプル。Cloud Schedulerが
`jobs.run` APIを叩いて1回実行→終了する。

### なぜVertex AI経由のGeminiか
RIZAP側の新規GCPプロジェクト内の権限(Vertex AI呼び出し)だけで完結させるため。
APIキーの発行・Secret Manager登録・失効管理が不要になる。Geminiは純正のGoogleモデルなので、
Model Garden経由のパートナーモデルのような追加の利用規約同意も不要。

### なぜOAuth(人間アカウント)でDrive/Sheetsにアクセスするか
サービスアカウントへのフォルダ共有ではなく、「ユーザーもログインできるRIZAP側の
Googleアカウント」を使う方針のため。`scripts/generate_oauth_token.py` で1回だけ
そのアカウントにログインして認可し、発行されたトークンをSecret Manager経由で
Cloud Run Jobsに渡す(トークンはアクセストークンの自動更新に対応)。

## 参考実装
`re-hatch-data/rizap_data_analytics_aget`(Slack×BigQuery分析エージェント)の
リポジトリ構成・deployスクリプト・ドキュメント構成を踏襲している。
