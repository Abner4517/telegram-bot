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
ADMIN_USER_ID = int(os.environ.get("AUTHORIZED_USER_ID", "0"))

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
else:
    logger.warning("No telegram_export.json found.")

PERSONAL_INFO = """اطلاعات شخصی تو:
- اسمت حسنه، بهت حصن هم میگن
- 14 سال و 9 ماهته
- اصفهان زندگی میکنی
- کارت سرپرست تایپ توی یه تیم برای مانهواست"""

SYSTEM_PROMPT = (
    PERSONAL_INFO + "\n\n"
    "تو یک دستیار هوشمند هستی که باید دقیقا مثل صاحب این اکانت تلگرام جواب بدی.\n\n"
    "تاریخچه چت های اخیر:\n" + (chat_context if chat_context else "تاریخچه ای یافت نشد.") + "\n\n"
    "بر اساس این چت ها سبک نوشتاری و لحن این شخص رو یاد بگیر و عین اون جواب بده.\n"
    "فقط فارسی جواب بده.\n"
    "مهم: آخر هر پیامت این ایموجی رو بذار: 😂\n"
    "مهم: اگه سوالی پرسیده شد که جواب دقیقش رو نمیدونی یا مربوط به اطلاعات شخصی هست که نداری، فقط بنویس: UNKNOWN"
)

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
    await update.message.reply_text("سلام! چطور میتونم کمکت کنم؟ 😂")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text
    chat_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name or "کاربر"

    if user_id == ADMIN_USER_ID and user_text.startswith("/reply"):
        parts = user_text.split(" ", 2)
        if len(parts) >= 3:
            target_chat_id = int(parts[1])
            reply_text = parts[2]
            await context.bot.send_message(chat_id=target_chat_id, text=reply_text)
            await update.message.reply_text("جواب فرستاده شد.")
        return

    if chat_id not in conversation_history:
        conversation_history[chat_id] = []

    conversation_history[chat_id].append({"role": "user", "content": user_text})
    if len(conversation_history[chat_id]) > 40:
        conversation_history[chat_id] = conversation_history[chat_id][-40:]

    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + conversation_history[chat_id]
        reply = ask_groq(messages)

        if "UNKNOWN" in reply:
            admin_msg = (
                "سوالی رسیده که جوابش رو نمیدونم!\n\n"
                "از: @" + str(username) + " (chat_id: " + str(chat_id) + ")\n"
                "سوال: " + user_text + "\n\n"
                "برای جواب دادن بنویس:\n"
                "/reply " + str(chat_id) + " جواب تو اینجا"
            )
            await context.bot.send_message(chat_id=ADMIN_USER_ID, text=admin_msg)
            await update.message.reply_text("سوال خوبیه! الان چک میکنم و بهت میگم. 😂")
        else:
            conversation_history[chat_id].append({"role": "assistant", "content": reply})
            await update.message.reply_text(reply)

    except Exception as e:
        logger.error("Error: " + str(e))
        await update.message.reply_text("یه مشکلی پیش اومد، دوباره امتحان کن.")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    conversation_history[chat_id] = []
    await update.message.reply_text("تاریخچه پاک شد.")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
    
