import os
import json
import logging
import requests
import traceback
import time
import asyncio

from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================= CONFIG =================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# ================= RATE LIMIT =================
last_request_time = {}
MIN_DELAY = 1  # ⬅️ هر کاربر هر 1 ثانیه یک درخواست
lock = asyncio.Lock()

# ================= HISTORY =================
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

    chat_context = "\n".join(messages_list[-150:])
else:
    logger.warning("No telegram_export.json found.")

# ================= SYSTEM PROMPT =================
PERSONAL_INFO = """
اطلاعات شخصی:
- اسم: حسنه
- 14 سال و 9 ماه
- اصفهان
- سرپرست تایپ مانهوا
"""

SYSTEM_PROMPT = (
    PERSONAL_INFO +
    "\n\nتاریخچه:\n" +
    (chat_context if chat_context else "ندارد") +
    "\n\nفقط فارسی جواب بده 😂"
)

# ================= MEMORY =================
conversation_history = {}

# ================= GROQ =================
def ask_groq(messages):
    url = "https://api.groq.com/openai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": messages,
        "max_tokens": 250  # ⬅️ کاهش فشار API
    }

    response = requests.post(url, headers=headers, json=payload)

    if response.status_code == 429:
        return "الان سرور شلوغه، یکم بعد دوباره امتحان کن 😂"

    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("سلام 😂")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conversation_history[chat_id] = []
    await update.message.reply_text("ریست شد")

# ================= HANDLER =================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text

    # ================= RATE LIMIT (1 sec) =================
    now = time.time()

    if chat_id in last_request_time:
        if now - last_request_time[chat_id] < MIN_DELAY:
            await update.message.reply_text("یکم صبر کن 😂")
            return

    last_request_time[chat_id] = now

    # ================= MEMORY =================
    if chat_id not in conversation_history:
        conversation_history[chat_id] = []

    conversation_history[chat_id].append({"role": "user", "content": user_text})
    conversation_history[chat_id] = conversation_history[chat_id][-20:]

    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        async with lock:  # ⬅️ جلوگیری از همزمانی درخواست‌ها
            messages = [{"role": "system", "content": SYSTEM_PROMPT}] + conversation_history[chat_id]
            reply = ask_groq(messages)

        conversation_history[chat_id].append({"role": "assistant", "content": reply})

        await update.message.reply_text(reply)

    except Exception as e:
        traceback.print_exc()
        await update.message.reply_text("خطا پیش اومد 😂")

# ================= MAIN =================
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
