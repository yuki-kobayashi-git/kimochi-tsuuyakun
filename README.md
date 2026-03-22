# きもち通訳ん 🌿

大切な人との気持ちをやさしく通訳してくれる LINE Bot です。

家族や友人に言いたいけど、うまく伝えられない気持ちを AI がやわらかく通訳して届けます。

## 機能

- **傾聴モード** — 悩みや愚痴を聴いて、やさしく寄り添います
- **伝言モード** — 攻撃的な言葉をやわらかく変換し、相手に届けます
- **イライラ検知** — メッセージからストレスを検知すると、伝言を提案します
- **複数人対応** — 1人が複数の相手と繋がれます

## 使い方

1. LINE Bot を友だち追加
2. 名前を登録
3. 招待コードを大切な人に送って繋がる
4. 悩みを話すと傾聴。「伝えて」と送ると伝言モードに

## 構築方法

### 必要なもの

- [LINE Developers](https://developers.line.biz/) アカウント（Messaging API チャネル）
- [Google AI Studio](https://aistudio.google.com/) の Gemini API キー
- [Railway](https://railway.app/) アカウント（GitHub連携）

### 1. リポジトリをフォーク

このリポジトリを Fork し、自分の GitHub アカウントにコピーします。

### 2. LINE Bot を作成

1. [LINE Developers](https://developers.line.biz/) にログイン
2. 新しい Messaging API チャネルを作成
3. 以下を控えておく：
   - **Channel access token**（Messaging API タブ → 発行）
   - **Bot basic ID**（`@xxx` の形式）

### 3. Gemini API キーを取得

1. [Google AI Studio](https://aistudio.google.com/) にアクセス
2. 「Get API Key」から API キーを作成

### 4. Railway にデプロイ

1. [Railway](https://railway.app/) に GitHub アカウントでログイン
2. 「New Project」→「Deploy from GitHub repo」→ フォークしたリポジトリを選択
3. **Database** → **PostgreSQL** を追加
4. PostgreSQL の `DATABASE_URL` をアプリの環境変数に接続（Railway の Reference Variable: `${{Postgres.DATABASE_URL}}`）
5. アプリの **Variables** に以下を設定：

| 変数名 | 値 |
|--------|-----|
| `LINE_CHANNEL_TOKEN` | LINE の Channel access token |
| `LINE_BOT_ID` | LINE Bot の Basic ID（`@xxx`） |
| `GEMINI_API_KEY` | Google Gemini の API キー |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}`（自動設定） |

6. **Settings** → **Networking** → 「Generate Domain」で公開 URL を取得

### 5. LINE Webhook を設定

1. LINE Developers → Messaging API → Webhook URL に以下を入力：
   ```
   https://あなたのドメイン.up.railway.app/webhook
   ```
2. 「Verify」を押して Success を確認
3. 「Use webhook」を ON にする

### ローカルで開発する場合

```bash
# 依存パッケージをインストール
pip install -r requirements.txt

# .env ファイルを作成（.env.example を参考に）
cp .env.example .env
# .env にAPIキー等を記入

# 起動
python app.py
```

ローカル実行時は [ngrok](https://ngrok.com/) 等で公開URLを作り、LINE Webhook に設定してください。

## 技術スタック

- Python / Flask
- LINE Messaging API
- Google Gemini AI（gemini-2.5-flash）
- PostgreSQL
- Railway（ホスティング）

## ライセンス

MIT
