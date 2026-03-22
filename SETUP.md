# きもち通訳ん — セットアップ手順

## 必要なもの

| ツール | 用途 |
|--------|------|
| Python 3.10+ | サーバー実行 |
| ngrok | ローカルPCをLINEに公開 |
| LINE Developers アカウント | LINE Bot作成 |
| Google AI Studio アカウント | Gemini APIキー取得 |

---

## STEP 1 — LINE Bot を作る

1. https://developers.line.biz/ にログイン
2. Provider を作成（例: きもち通訳ん）
3. **Messaging API** チャネルを作成
4. チャネル設定 → **Channel access token** をコピー

---

## STEP 2 — Gemini API キーを取得

1. https://aistudio.google.com にログイン
2. 「Get API Key」→ 新しいAPIキーを作成
3. キーをコピー

---

## STEP 3 — .env ファイルを作る

```
cp .env.example .env
```

`.env` を開いて、STEP1・STEP2 のキーを貼り付ける。

```
LINE_CHANNEL_TOKEN=eyJhbGci...
GEMINI_API_KEY=AIzaSy...
```

---

## STEP 4 — Python 環境を用意

```bash
pip install -r requirements.txt
```

---

## STEP 5 — サーバーを起動

```bash
python app.py
```

`🌿 きもち通訳ん 起動中 → http://localhost:5000` が出ればOK。

---

## STEP 6 — ngrok で公開

別のターミナルで:

```bash
ngrok http 5000
```

表示される URL をコピー（例: `https://xxxx.ngrok-free.app`）

---

## STEP 7 — LINE Webhook を設定

1. LINE Developers → チャネル → Messaging API
2. **Webhook URL** に入力:
   ```
   https://xxxx.ngrok-free.app/webhook
   ```
3. **Verify** ボタンを押して「Success」が出ればOK
4. **Use webhook** を ON にする

---

## 使い方

### 初回
1. 親・子 それぞれが LINE Bot を友達追加
2. 最初のメッセージを送ると名前を聞かれる
3. 名前を入力 → **招待コード（6文字）** が発行される

### 繋がる
1. どちらかが招待コードを相手に教える
2. 相手がきもち通訳んに招待コードを送る → 繋がり完了

### 普段の使い方
- 普通に話しかけると相談相手として会話
- イライラを話すと「相手に通訳して伝えましょうか？」と聞いてくる
- 「はい」→ 伝えたい内容を入力 → やわらかく翻訳して相手に送信

### コマンド
| 送るテキスト | 動作 |
|-------------|------|
| `ヘルプ` | 招待コードと使い方を表示 |
| `仲裁して` | 仲裁モードに直接入る |
| `キャンセル` | 仲裁を中止して通常に戻る |

---

## ファイル構成

```
Shuttle/
├── app.py          メインアプリ
├── requirements.txt ライブラリ
├── .env            APIキー（git管理しない）
├── .env.example    テンプレート
├── SETUP.md        この手順書
└── kimochi.db      会話データ（自動生成）
```
