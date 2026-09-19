import os
from flask import Flask, request
from dotenv import load_dotenv
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, JoinEvent
from openai import OpenAI


load_dotenv()

app = Flask(__name__)


line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))


def _load_authorized_user_ids():
    raw = os.getenv("LINE_AUTHORIZED_USER_IDS", "")
    return {user_id.strip() for user_id in raw.split(",") if user_id.strip()}

AUTHORIZED_USER_IDS = _load_authorized_user_ids()

def _get_all_member_ids(chat_id, is_room=False):
    member_ids = set()
    start = None
    fetch_ids = (
        line_bot_api.get_room_member_ids if is_room else line_bot_api.get_group_members_ids
    )
    while True:
        response = fetch_ids(chat_id, start=start)
        member_ids.update(response.member_ids)
        if not response.next:
            break
        start = response.next
    return member_ids

def _chat_has_authorized_member(chat_id, is_room=False):
    if not AUTHORIZED_USER_IDS:
        print("WARNING: LINE_AUTHORIZED_USER_IDS is empty — rejecting all group invites")
        return False
    try:
        member_ids = _get_all_member_ids(chat_id, is_room=is_room)
        return bool(AUTHORIZED_USER_IDS & member_ids)
    except Exception as e:
        print(f"Failed to verify group members for {chat_id}: {e}")
        return False

def _leave_chat(chat_id, is_room=False):
    if is_room:
        line_bot_api.leave_room(chat_id)
    else:
        line_bot_api.leave_group(chat_id)

ollama_client = OpenAI(base_url="", api_key="")
OLLAMA_MODEL = ""

SYSTEM_PROMPT = """prompt"""

#Memory
chat_histories = {}

def get_reply(user_id, user_message):
    if user_id not in chat_histories:
        chat_histories[user_id] = []

    history = chat_histories[user_id]

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in history:
        role = "assistant" if msg["role"] == "model" else msg["role"]
        messages.append({"role": role, "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    response = ollama_client.chat.completions.create(
        model=OLLAMA_MODEL,
        messages=messages,
        max_tokens=300,
    )

    reply_text = response.choices[0].message.content

    history.append({"role": "user", "content": user_message})
    history.append({"role": "model", "content": reply_text})

    if len(history) > 8:
        history = history[-8:]

    chat_histories[user_id] = history
    return reply_text

@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    print("WEBHOOK CALLED:", body[:100])
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("Invalid signature")
    except Exception as e:
        print("ERROR:", e)
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    print("USER ID:", user_id)
    text = event.message.text.replace("@Dee", "").strip()
    if not text:
        text = event.message.text
    reply = get_reply(user_id, text)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

@handler.add(JoinEvent)
def handle_join(event):
    source = event.source
    group_id = getattr(source, "group_id", None)
    room_id = getattr(source, "room_id", None)
    chat_id = group_id or room_id
    is_room = room_id is not None

    if not chat_id:
        return

    if not _chat_has_authorized_member(chat_id, is_room=is_room):
        chat_type = "room" if is_room else "group"
        print(f"Unauthorized {chat_type} invite ({chat_id}) — leaving")
        try:
            _leave_chat(chat_id, is_room=is_room)
        except Exception as e:
            print(f"Failed to leave {chat_type} {chat_id}: {e}")
        return

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="text at line 140")
    )

#if __name__ == "__main__":
#    app.run(port=add port here!)
