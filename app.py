"""
きもち通訳ん
────────────────────────────────────────────────────────────
大切な人との気持ちをやさしく通訳してくれる LINE Bot。

複数人対応:
  親A ↔ 子C, 子D
  親B ↔ 子C, 子D
  のように、1人が複数人と繋がれる。
  伝言時は「誰に伝えますか？」と選択肢を出す。
────────────────────────────────────────────────────────────
"""

import os
import re
import random
import string

import psycopg2
import psycopg2.extras
from flask import Flask, request
import requests
import google.generativeai as genai
from dotenv import load_dotenv
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

load_dotenv()

app = Flask(__name__)

LINE_TOKEN     = os.getenv("LINE_CHANNEL_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
LINE_BOT_ID    = os.getenv("LINE_BOT_ID", "")
DATABASE_URL   = os.getenv("DATABASE_URL", "")

genai.configure(api_key=GEMINI_API_KEY)
gemini = genai.GenerativeModel("gemini-2.5-flash")


# ─────────────────────────────────────────────────────────────
# DB
# ─────────────────────────────────────────────────────────────

def _con():
    con = psycopg2.connect(DATABASE_URL)
    return con


def _init_db_once():
    """gunicorn 経由でもDB初期化されるようモジュール読み込み時に実行"""
    con = _con()
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            line_id          TEXT PRIMARY KEY,
            name             TEXT,
            invite_code      TEXT,
            state            TEXT DEFAULT 'registering',
            mediation_target TEXT
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS relations (
            user_a TEXT,
            user_b TEXT,
            UNIQUE(user_a, user_b)
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id      SERIAL PRIMARY KEY,
            line_id TEXT,
            role    TEXT,
            text    TEXT,
            ts      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    con.commit()
    cur.close()
    con.close()

_init_db_once()

def init_db():
    _init_db_once()


def get_user(line_id: str) -> dict | None:
    con = _con()
    cur = con.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM users WHERE line_id=%s", (line_id,))
    row = cur.fetchone()
    cur.close()
    con.close()
    return dict(row) if row else None


def upsert_user(line_id: str, **kw):
    con = _con()
    cur = con.cursor()
    cur.execute("SELECT 1 FROM users WHERE line_id=%s", (line_id,))
    if not cur.fetchone():
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        cur.execute(
            "INSERT INTO users (line_id, invite_code, state) VALUES (%s,%s,%s)",
            (line_id, code, "registering"),
        )
    if kw:
        sets = ", ".join(f"{k}=%s" for k in kw)
        vals = list(kw.values()) + [line_id]
        cur.execute(f"UPDATE users SET {sets} WHERE line_id=%s", vals)
    con.commit()
    cur.close()
    con.close()


def find_by_invite(code: str) -> dict | None:
    con = _con()
    cur = con.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM users WHERE invite_code=%s", (code.upper(),))
    row = cur.fetchone()
    cur.close()
    con.close()
    return dict(row) if row else None


def add_relation(a: str, b: str):
    """2人をリンクする（双方向）"""
    con = _con()
    cur = con.cursor()
    cur.execute("INSERT INTO relations (user_a, user_b) VALUES (%s,%s) ON CONFLICT DO NOTHING", (a, b))
    cur.execute("INSERT INTO relations (user_a, user_b) VALUES (%s,%s) ON CONFLICT DO NOTHING", (b, a))
    con.commit()
    cur.close()
    con.close()


def get_partners(line_id: str) -> list[dict]:
    """繋がっている全員を返す"""
    con = _con()
    cur = con.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT u.* FROM relations r JOIN users u ON u.line_id = r.user_b WHERE r.user_a=%s",
        (line_id,),
    )
    rows = cur.fetchall()
    cur.close()
    con.close()
    return [dict(r) for r in rows]


def get_partner_by_name(line_id: str, name: str) -> dict | None:
    """名前で相手を探す"""
    partners = get_partners(line_id)
    for p in partners:
        if p.get("name") == name:
            return p
    return None


def get_mediation_target(line_id: str) -> dict | None:
    """現在の伝言相手を取得"""
    user = get_user(line_id)
    if not user or not user.get("mediation_target"):
        return None
    return get_user(user["mediation_target"])


def save_msg(line_id: str, role: str, text: str):
    con = _con()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO messages (line_id, role, text) VALUES (%s,%s,%s)",
        (line_id, role, text),
    )
    con.commit()
    cur.close()
    con.close()


def get_history(line_id: str, limit: int = 8) -> list[tuple]:
    con = _con()
    cur = con.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT role, text FROM messages WHERE line_id=%s ORDER BY ts DESC LIMIT %s",
        (line_id, limit),
    )
    rows = cur.fetchall()
    cur.close()
    con.close()
    return [(r["role"], r["text"]) for r in reversed(rows)]


# ─────────────────────────────────────────────────────────────
# LINE API
# ─────────────────────────────────────────────────────────────

def _line_headers():
    return {
        "Authorization": f"Bearer {LINE_TOKEN}",
        "Content-Type": "application/json",
    }


def reply(reply_token: str, text: str):
    requests.post(
        "https://api.line.me/v2/bot/message/reply",
        headers=_line_headers(),
        json={"replyToken": reply_token, "messages": [{"type": "text", "text": text}]},
    )


def invite_card(code: str) -> str:
    add_url = f"https://line.me/ti/p/{LINE_BOT_ID}" if LINE_BOT_ID else "（LINE Bot を友達追加）"
    return (
        "👇 このメッセージをそのまま相手に転送してください\n"
        "─────────────────────\n"
        "きもち通訳んに招待されました🌿\n\n"
        f"① 下のリンクから友達追加\n{add_url}\n\n"
        f"② Bot に「{code}」と送る\n"
        "─────────────────────"
    )


def push(user_id: str, text: str):
    requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers=_line_headers(),
        json={"to": user_id, "messages": [{"type": "text", "text": text}]},
    )


# ─────────────────────────────────────────────────────────────
# AI
# ─────────────────────────────────────────────────────────────

_PERSONA_LISTEN = """あなたは「きもち通訳ん」です。
家族や友人との関係に悩む人の話を聴く、LINEの相談相手です。
カウンセラーではなく「信頼できる友人」のような存在です。

## 基本姿勢
- 今まさにユーザー本人と直接話している。第三者への伝言ではない
- 「〇〇さんが〜とおっしゃっていました」のような第三者口調は絶対に使わない
- 相手の話をまず受け止めることを最優先にする
- 解決策を急がず、相手が「わかってもらえた」と感じることを大切にする
- 正解を教えるのではなく、相手が自分で気づけるように寄り添う

## 話し方のルール
- 「ですます調」をベースにしつつ、少しカジュアルに（「〜ですよね」「〜かもしれませんね」）
- 1回の返答は2〜5文。長くなりすぎないこと
- 箇条書きやリストは使わない。自然な会話文で返す
- 絵文字は使わない

## 会話の進め方
- 最初の1〜2往復は、とにかく聴くことに徹する。気持ちを受け止め、短く共感を返す
- 相手が状況を話してくれたら、理解を深めるために1つだけ質問する。一度に複数の質問はしない
- 十分に話を聴いた後で、相手が求めていそうなら控えめに視点の提示や提案をする
  → 「こういう見方もあるかもしれません」のように、押しつけではなく選択肢として出す
- 相手が感情的になっているときは、アドバイスよりも気持ちの言語化を優先する
  → 「それは悔しいですよね」「そう思うのは自然なことだと思います」

## やってはいけないこと
- 相手の判断を無条件に肯定しすぎない（「あなたは絶対正しい」のような断言は避ける）
- 相手の家族・友人を一方的に悪者にしない
- 「頑張って」「大丈夫」を安易に使わない
- 長い語りや説教をしない

## 大切にすること
- 相手のペースに合わせる。短文には短く返す
- 相手の言葉をそのまま使って返すことで、聴いていることを伝える
  → 相手が「母がしんどい」と言ったら「お母さんのことがしんどいんですね」
- 毎回の返答の前に、相手が今何を求めているか（共感？質問への回答？アドバイス？ただ聴いてほしい？）を考えてから返す
"""

_PERSONA_TRANSLATE = """あなたは「きもち通訳ん」です。
家族や大切な人の気持ちをやわらかく通訳してくれる、やさしいAIです。

ルール:
- 攻撃的・感情的な言葉をやわらかい表現に変換する
- どちらかの味方にならず、中立を保つ
- 短く、温かく、敬語で話す
- 説教や長い解説はしない
"""


def ai_chat(line_id: str, my_name: str, text: str) -> str:
    history = get_history(line_id)
    hist_text = "\n".join(
        f"{'ユーザー' if r == 'user' else 'きもち通訳ん'}: {t}" for r, t in history
    )

    prompt = f"""{_PERSONA_LISTEN}
ユーザーの名前: {my_name}さん

会話履歴:
{hist_text}

{my_name}さん: {text}
きもち通訳ん:"""

    return gemini.generate_content(prompt).text.strip()


def translate_message(sender_name: str, receiver_name: str, raw: str) -> str:
    prompt = f"""{_PERSONA_TRANSLATE}
{sender_name}さんが{receiver_name}さんに伝えたいことがあります。
以下のメッセージを、攻撃的な表現を取り除き、気持ちや本音だけを温かく{receiver_name}さんへ伝えてください。

元のメッセージ: {raw}

{receiver_name}さんへの伝言（「{sender_name}さんは〜」という形式で）:"""

    return gemini.generate_content(prompt).text.strip()


_FRUSTRATION_WORDS = [
    "むかつく", "イライラ", "うざい", "腹立つ", "怒", "嫌い",
    "困ってる", "言っても聞かない", "わかってくれない",
    "やめてほしい", "なんで毎回", "ひどい", "つらい", "もう限界",
    "どうにかして", "きつい", "ストレス",
]


def is_frustrated(text: str) -> bool:
    return any(w in text for w in _FRUSTRATION_WORDS)


# ─────────────────────────────────────────────────────────────
# ヘルパー: 伝言相手の選択
# ─────────────────────────────────────────────────────────────

def partner_list_text(partners: list[dict]) -> str:
    """番号付きの相手リストを作る"""
    lines = []
    for i, p in enumerate(partners, 1):
        lines.append(f"{i}. {p.get('name', '???')}")
    return "\n".join(lines)


def start_mediation(line_id: str, reply_token: str, partner: dict):
    """伝言モードを開始する（相手が決まった後）"""
    upsert_user(line_id, state="mediation_input", mediation_target=partner["line_id"])
    reply(
        reply_token,
        f"{partner['name']}さんに伝えたいことを、そのままお話しください🌿\n"
        "私が気持ちをやさしく通訳してお伝えします。",
    )


def ask_who(line_id: str, reply_token: str, partners: list[dict], prefix: str = ""):
    """誰に伝えるか聞く"""
    upsert_user(line_id, state="choosing_target")
    msg = prefix
    if prefix:
        msg += "\n\n"
    msg += "誰に伝えますか？番号で選んでください。\n\n"
    msg += partner_list_text(partners)
    reply(reply_token, msg)


# ─────────────────────────────────────────────────────────────
# Message handler
# ─────────────────────────────────────────────────────────────

def handle(line_id: str, reply_token: str, text: str):
    text = text.strip()

    # ── 新規ユーザー ──────────────────────────────────────
    user = get_user(line_id)
    if not user:
        upsert_user(line_id)
        reply(
            reply_token,
            "はじめまして🌿 私は「きもち通訳ん」です。\n"
            "大切な人との気持ちをやさしく通訳します。\n\n"
            "まず、あなたのお名前を教えてください。",
        )
        return

    state   = user.get("state", "registering")
    my_name = user.get("name") or "あなた"

    # ── 名前登録 ──────────────────────────────────────────
    if state == "registering":
        name = text
        upsert_user(line_id, name=name, state="normal")
        code = get_user(line_id)["invite_code"]
        reply(
            reply_token,
            f"{name}さん、よろしくお願いします🌿\n\n"
            f"📎 あなたの招待コード: {code}\n\n"
            "下のメッセージを大切な人に転送してください。\n"
            "相手がコードを送ってくれると繋がります。",
        )
        push(line_id, invite_card(code))
        return

    # ── ヘルプ ────────────────────────────────────────────
    if text in ["ヘルプ", "help", "？", "?", "使い方"]:
        code = user.get("invite_code", "")
        partners = get_partners(line_id)
        if partners:
            names = "、".join(p["name"] for p in partners if p.get("name"))
            partner_info = f"繋がっている相手: {names}"
        else:
            partner_info = "まだ誰とも繋がっていません"
        reply(
            reply_token,
            f"【きもち通訳ん の使い方】\n\n"
            f"📎 あなたの招待コード: {code}\n"
            f"{partner_info}\n\n"
            "・招待コードを相手に送ると繋がれます（何人でもOK）\n"
            "・イライラや悩みを話すと、相手に気持ちを通訳してお伝えできます\n"
            "・「伝えて」と送るといつでも伝言モードになります",
        )
        if not partners:
            push(line_id, invite_card(code))
        return

    # ── 招待コード入力 ────────────────────────────────────
    if re.match(r"^[A-Za-z0-9]{6}$", text):
        other = find_by_invite(text)
        if other and other["line_id"] != line_id:
            add_relation(line_id, other["line_id"])
            other_name = other.get("name") or "相手の方"
            reply(
                reply_token,
                f"{other_name}さんと繋がりました🎉\n"
                "これからお二人の気持ちを通訳します🌿",
            )
            push(
                other["line_id"],
                f"{my_name}さんと繋がりました🌿\n"
                "きもち通訳んがお二人の間に入ります。",
            )
            return
        elif other and other["line_id"] == line_id:
            reply(reply_token, "それはご自身の招待コードです😊")
            return

    # ── 仲裁相手の選択中 ─────────────────────────────────
    if state == "choosing_target":
        partners = get_partners(line_id)
        # 番号で選択
        if text.isdigit():
            idx = int(text) - 1
            if 0 <= idx < len(partners):
                start_mediation(line_id, reply_token, partners[idx])
                return
        # 名前で選択
        target = get_partner_by_name(line_id, text)
        if target:
            start_mediation(line_id, reply_token, target)
            return
        reply(reply_token, "番号か名前で選んでください🌿\n\n" + partner_list_text(partners))
        return

    # ── 伝言モード: 確認待ち ──────────────────────────────
    if state == "waiting_mediation":
        yes_words = {"はい", "お願い", "yes", "する", "お願いします", "うん", "いいよ"}
        if text.lower() in yes_words or any(w in text for w in yes_words):
            partners = get_partners(line_id)
            if not partners:
                upsert_user(line_id, state="normal")
                reply(reply_token, "繋がっている相手がいないため、伝言できません🌿")
                return
            if len(partners) == 1:
                start_mediation(line_id, reply_token, partners[0])
            else:
                ask_who(line_id, reply_token, partners)
        else:
            upsert_user(line_id, state="normal")
            reply(reply_token, "わかりました。いつでもお声がけくださいね🌿")
        return

    # ── 伝言モード: メッセージ入力 ──────────────────────
    if state in ("mediation_input", "mediation_reply"):
        # 「終わり」で伝言モードを終了
        if text in ["終わり", "おわり", "終了", "キャンセル", "cancel", "やめる", "もどる"]:
            target = get_mediation_target(line_id)
            if target:
                upsert_user(target["line_id"], state="normal", mediation_target=None)
                push(target["line_id"], "伝言モードが終了しました🌿")
            upsert_user(line_id, state="normal", mediation_target=None)
            reply(reply_token, "伝言モードを終了しました🌿\nまたいつでも相談してくださいね。")
            return

        target = get_mediation_target(line_id)
        if not target:
            upsert_user(line_id, state="normal", mediation_target=None)
            reply(reply_token, "相手が見つかりませんでした。もう一度試してください🌿")
            return

        target_name = target.get("name") or "相手の方"
        translated  = translate_message(my_name, target_name, text)

        push(
            target["line_id"],
            f"💬 {my_name}さんから気持ちが届きました:\n\n{translated}\n\n"
            "「終わり」で伝言モードを終了できます🌿",
        )
        # 相手も伝言モードに入れる（返事をそのまま送れるように）
        upsert_user(target["line_id"], state="mediation_input", mediation_target=line_id)
        # 自分も伝言モードのまま
        upsert_user(line_id, state="mediation_input")

        reply(
            reply_token,
            f"✓ {target_name}さんにやさしく伝えました🌿\n"
            "「終わり」で伝言モードを終了できます。",
        )
        return

    # ── 伝言リクエスト（明示） ────────────────────────────
    if text in ["伝えて", "伝言して", "仲裁して", "なかだちして", "間に入って"]:
        partners = get_partners(line_id)
        if not partners:
            reply(reply_token, "まだ繋がっている相手がいません。招待コードで繋がってから使ってみてください🌿")
            return
        if len(partners) == 1:
            start_mediation(line_id, reply_token, partners[0])
        else:
            ask_who(line_id, reply_token, partners)
        return

    # ── 通常会話 ──────────────────────────────────────────
    save_msg(line_id, "user", text)
    partners = get_partners(line_id)

    # イライラ検知 → 伝言を提案
    if partners and is_frustrated(text):
        ai_response = ai_chat(line_id, my_name, text)
        save_msg(line_id, "assistant", ai_response)
        upsert_user(line_id, state="waiting_mediation")

        if len(partners) == 1:
            target_name = partners[0].get("name") or "相手の方"
            reply(
                reply_token,
                f"{ai_response}\n\n"
                "─────────────────\n"
                f"💬 {target_name}さんにも気持ちを通訳してお伝えしましょうか？\n"
                "「はい」か「いいえ」で教えてください。",
            )
        else:
            reply(
                reply_token,
                f"{ai_response}\n\n"
                "─────────────────\n"
                "💬 繋がっている方に気持ちを通訳してお伝えしましょうか？\n"
                "「はい」か「いいえ」で教えてください。",
            )
        return

    # 通常AI返答
    ai_response = ai_chat(line_id, my_name, text)
    save_msg(line_id, "assistant", ai_response)
    reply(reply_token, ai_response)


# ─────────────────────────────────────────────────────────────
# Webhook
# ─────────────────────────────────────────────────────────────

@app.route("/webhook", methods=["POST"])
def webhook():
    body = request.json
    if not body or "events" not in body:
        return "OK"

    for event in body.get("events", []):
        if event.get("type") != "message":
            continue
        if event["message"].get("type") != "text":
            continue

        line_id     = event["source"]["userId"]
        reply_token = event["replyToken"]
        text        = event["message"]["text"]

        try:
            handle(line_id, reply_token, text)
        except Exception as e:
            print(f"[ERROR] {e}")
            reply(reply_token, "うまく聞き取れませんでした。もう一度話しかけてみてください🌿")

    return "OK"


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    print(f"🌿 きもち通訳ん 起動中 → http://localhost:{port}")
    app.run(host="0.0.0.0", port=port)
