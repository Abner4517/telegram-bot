import os
import json
import logging
import requests
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
AUTHORIZED_USER_ID = int(os.environ.get("AUTHORIZED_USER_ID", "0"))

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
                    messages_list.append(sender + ": " + text)
    recent = messages_list[-300:]
    chat_context = "\n".join(recent)
    logger.info("Loaded " + str(len(recent)) + " messages from export.")
else:
    logger.warning("No telegram_export.json found.")

SYSTEM_PROMPT = "تو یک دستیار هوشمند هستی که باید دقیقا مثل صاحب این اکانت تلگرام جواب بدی.\n\nتاریخچه چت های اخیر:\n" + (chat_context if chat_context else "تاریخچه ای یافت نشد.") + "\n\nبر اساس این چت ها سبک نوشتاری و لحن این شخص رو یاد بگیر و عین اون جواب بده. فقط فارسی جواب بده."

conversation_history = {}

def ask_groq(messages):
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": "Bearer " + GROQ_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": messages,
        "max_tokens": 500
    }
    response = requests.post(url, headers=headers, json=payload)
    return response.json()["choices"][0]["message"]["content"]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if AUTHORIZED_USER_ID and user_id != AUTHORIZED_USER_ID:
        await update.message.reply_text("access denied")
        return
    await update.message.reply_text("bot is ready!")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if AUTHORIZED_USER_ID and user_id != AUTHORIZED_USER_ID:
        await update.message.reply_text("access denied")
        return
    user_text = update.message.text
    chat_id = update.effective_chat.id
    if chat_id not in conversation_history:
        conversation_history[chat_id] = []
    conversation_history[chat_id].append({"role": "user", "content": user_text})
    if len(conversation_history[chat_id]) > 40:
        conversation_history[chat_id] = conversation_history[chat_id][-40:]
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + conversation_history[chat_id]
        reply = ask_groq(messages)
        conversation_history[chat_id].append({"role": "assistant", "content": reply})
        await update.message.reply_text(reply)
    except Exception as e:
        logger.error("Error: " + str(e))
        await update.message.reply_text("error occurred. try again.")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conversation_history[chat_id] = []
    await update.message.reply_text("history cleared.")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
