"""RIZAP側アカウントでの初回OAuth認可（1回だけ、ローカルで実行）。

このスクリプトを実行するとブラウザが開き、RIZAP側の対象Googleアカウントでログイン・
Drive/Sheetsへのアクセス許可を行う。発行されたトークンをCloud Run Jobsに持たせることで、
サービスアカウントへのフォルダ共有をせずに、そのアカウント自身の権限でシートを読み書きできる。

事前準備:
  GCPコンソール（RIZAP側の新規プロジェクト）→ APIとサービス → 認証情報 →
  「OAuthクライアントIDを作成」（アプリケーションの種類: デスクトップアプリ）→
  ダウンロードしたJSONを、このリポジトリ直下に credentials/oauth-client.json として配置する
  （credentials/ は .gitignore 済みなのでコミットされない）

使い方:
  python -m scripts.generate_oauth_token
  → ブラウザでRIZAP側の対象Googleアカウントにログイン・許可
  → credentials/oauth-token.json が生成される
  → 以下でSecret Managerに登録し、Cloud Run Jobsにボリュームとしてマウントする
      gcloud secrets create oauth-token --data-file=credentials/oauth-token.json
"""

import pathlib

from google_auth_oauthlib.flow import InstalledAppFlow

from src.sheets_client import SCOPES

CLIENT_SECRET_FILE = pathlib.Path("credentials/oauth-client.json")
TOKEN_FILE = pathlib.Path("credentials/oauth-token.json")


def main() -> None:
    if not CLIENT_SECRET_FILE.exists():
        raise SystemExit(
            f"{CLIENT_SECRET_FILE} が見つかりません。\n"
            "GCPコンソールでOAuthクライアント（デスクトップアプリ）を作成し、JSONを配置してください。"
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_FILE), SCOPES)
    creds = flow.run_local_server(port=0)

    TOKEN_FILE.parent.mkdir(exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")

    print(f"OK: {TOKEN_FILE} を生成しました。")
    print("次のコマンドでSecret Managerへ登録してください:")
    print(f"  gcloud secrets create oauth-token --data-file={TOKEN_FILE}")


if __name__ == "__main__":
    main()
