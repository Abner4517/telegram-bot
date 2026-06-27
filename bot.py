import os
import json
import logging
import requests
import traceback

from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
    ContextTypes,
    CommandHandler
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================= CONFIG =================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# ================= LOAD CHAT HISTORY =================
chat_context = ""
export_path = "telegram_export.json"

if os.path.exists(export_path):
    with open(export_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    messages_list = []
    chats = data.get("chats", {}).get("list", [data]) if "chats" in data else [data]

    for chat in chats:
        for msg in chat.get("messages", []):
            if msg.get("type") == "message" and isinstance(msg.get("text"), str):
                sender = msg.get("from", "unknown")
                text = msg["text"].strip()
                if text:
                    messages_list.append(f"{sender}: {text}")

    recent = messages_list[-200:]
    chat_context = "\n".join(recent)
else:
    logger.warning("telegram_export.json not found.")

# ================= SYSTEM PROMPT =================
PERSONAL_INFO = """
اطلاعات شخصی تو:
- اسمت حسنه، بهت حصن هم میگن
- 14 سال و 9 ماهته
- اصفهان زندگی میکنی
- کارت سرپرست تایپ توی یه تیم برای مانهواست
"""

SYSTEM_PROMPT = (
    PERSONAL_INFO + "\n\n"
    "تو یک دستیار هوشمند هستی که باید مثل صاحب این اکانت جواب بده.\n"
    "لحن و سبک نوشتار را از تاریخچه یاد بگیر.\n"
    "فقط فارسی جواب بده.\n"
    "آخر هر پیام این ایموجی را اضافه کن: 😂\n\n"
    "تاریخچه چت:\n" +
    (chat_context if chat_context else "ندارد")
)

# ================= MEMORY =================
conversation_history = {}

# ================= GROQ API =================
def ask_groq(messages):
    url = "https://api.groq.com/openai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": messages,
        "max_tokens": 500
    }

    response = requests.post(url, headers=headers, json=payload)

    # برای دیباگ
    if response.status_code != 200:
        print("Groq Error:", response.text)

    response.raise_for_status()

    data = response.json()
    return data["choices"][0]["message"]["content"]

# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام! چطور میتونم کمکت کنم؟ 😂")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conversation_history[chat_id] = []
    await update.message.reply_text("تاریخچه پاک شد.")

# ================= MESSAGE HANDLER =================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text
    username = update.effective_user.username or update.effective_user.first_name or "کاربر"

    if chat_id not in conversation_history:
        conversation_history[chat_id] = []

    conversation_history[chat_id].append({
        "role": "user",
        "content": user_text
    })

    # محدود کردن حافظه
    conversation_history[chat_id] = conversation_history[chat_id][-40:]

    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ] + conversation_history[chat_id]

        reply = ask_groq(messages)

        # همیشه خودش جواب می‌دهد (بدون UNKNOWN و بدون ادمین)
        conversation_history[chat_id].append({
            "role": "assistant",
            "content": reply
        })

        await update.message.reply_text(reply)

    except Exception as e:
        traceback.print_exc()
        logger.exception(e)
        await update.message.reply_text("یه خطایی پیش اومد، دوباره امتحان کن 😂")

# ================= MAIN =================
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
