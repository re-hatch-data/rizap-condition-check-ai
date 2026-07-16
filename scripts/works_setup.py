"""LINE WORKS連携のセットアップ補助CLI（連携ミーティング当日に使う）。

前提: Developer Consoleで発行した認証情報を works-bot.json にまとめておく
（形式は src/works_client.py のdocstring参照。パスは WORKS_BOT_CONFIG で変更可）。

使い方:
  1. トークルームを新規作成し、channelIdを表示する（Botがオーナーになる）:
     python scripts/works_setup.py create-channel \\
         --title "RIZAP コンディションAIコメント" \\
         --members trainer1@example.com,trainer2@example.com

  2. 表示されたchannelIdを設定JSONの channel_id に追記してからテスト送信:
     python scripts/works_setup.py test-send
"""

import argparse

from src.config import settings
from src.works_client import WorksClient, load_works_config

# 配信イメージの検討用サンプル（実際の文面・形式はミーティングで決定する）
SAMPLE_DIGEST = """【コンディションAIコメント】2026-07-17（サンプル）

■ 001_山田太郎
昨夜は就寝が普段より1時間ほど遅く、睡眠も5時間台と短めでした。本日は業務負荷が高い予定とのことなので、こまめな休憩と早めの就寝を意識できると良さそうです。

■ 002_鈴木花子
睡眠・ストレスとも安定しています。トレーニング開始後、総睡眠時間が平均30分ほど伸びており良い傾向です。この調子で維持しましょう。

※これはサンプルです。実際の配信内容・形式は要件定義で決定します"""


def main() -> None:
    parser = argparse.ArgumentParser(description="LINE WORKS連携のセットアップ補助")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create-channel", help="Botオーナーのトークルームを作成してchannelIdを表示")
    p_create.add_argument("--title", required=True, help="トークルーム名")
    p_create.add_argument("--members", required=True, help="参加メンバーのユーザーID（メール形式）をカンマ区切りで")

    p_test = sub.add_parser("test-send", help="設定済みトークルームへテスト送信")
    p_test.add_argument("--text", default="【テスト】コンディションAIコメントのLINE WORKS連携テストです")
    p_test.add_argument("--channel-id", default="", help="未指定なら設定JSONの channel_id を使う")
    p_test.add_argument(
        "--sample-digest",
        action="store_true",
        help="実際の配信イメージ（ダイジェスト形式のサンプル文面）を送る。文面検討用",
    )

    args = parser.parse_args()

    config = load_works_config(settings.works_bot_config)
    if config is None:
        raise SystemExit(
            f"設定ファイルが見つかりません: {settings.works_bot_config}\n"
            "Developer Consoleの認証情報をJSONにまとめて配置してください（WORKS_BOT_CONFIGでパス変更可）。"
        )
    client = WorksClient(config)

    if args.command == "create-channel":
        members = [m.strip() for m in args.members.split(",") if m.strip()]
        channel_id = client.create_channel(args.title, members)
        print(f"channelId: {channel_id}")
        print("この値を設定JSONの channel_id に追記してください。")
    else:
        text = SAMPLE_DIGEST if args.sample_digest else args.text
        client.send_text(text, channel_id=args.channel_id or None)
        print("送信しました。トークルームに届いていることを確認してください。")


if __name__ == "__main__":
    main()
