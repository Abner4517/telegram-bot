import os
import json
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
from groq import Groq

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
AUTHORIZED_USER_ID = int(os.environ.get("AUTHORIZED_USER_ID", "0"))

client = Groq(api_key=GROQ_API_KEY)

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
                sender = msg.get("from", "نامشخص")
                text = msg["text"].strip()
                if text:
                    messages_list.append(f"{sender}: {text}")
    recent = messages_list[-300:]
    chat_context = "\n".join(recent)
    logger.info(f"Loaded {len(recent)} messages from export.")
else:
    logger.warning("No telegram_export.json found. Running without chat history.")

SYSTEM_PROMPT = f"""تو یک دستیار هوشمند هستی که باید دقیقاً مثل صاحب این اکانت تلگرام جواب بدی.
برای این کار، تاریخچه چت های اخیر این شخص رو داری:
--- شروع تاریخچه چت ---
{chat_context if chat_context else "تاریخچه ای یافت نشد."}
--- پایان تاریخچه چت ---
بر اساس این چت ها:
- سبک نوشتاری، لحن، و شیوه پاسخ دهی این شخص رو یاد بگیر
- از همون کلمات، عبارات، و اختصارات که این شخص استفاده می کنه استفاده کن
- طول پیام ها رو مشابه حفظ کن
- اگه این شخص شوخ طبعه، شوخ باش. اگه رسمیه، رسمی باش.
- فقط به فارسی جواب بده مگه اینکه مکالمه به زبان دیگه ای باشه
مهم: تو داری به جای این شخص جواب می دی، نه به عنوان یه ربات."""

conversation_history = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if AUTHORIZED_USER_ID and user_id != AUTHORIZED_USER_ID:
        await update.message.reply_text("دسترسی مجاز نیست.")
        return
    await update.message.reply_text("ربات آماده است! پیام بفرست.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if AUTHORIZED_USER_ID and user_id != AUTHORIZED_USER_ID:
        await update.message.reply_text("دسترسی مجاز نیست.")
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
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            max_tokens=500
        )
        reply = response.choices[0].message.content
        conversation_history[chat_id].append({"role": "assistant", "content": reply})
        await update.message.reply_text(reply)
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("خطایی رخ داد. لطفا دوباره امتحان کن.")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if AUTHORIZED_USER_ID and user_id != AUTHORIZED_USER_ID:
        return
    chat_id = update.effective_chat.id
    conversation_history[chat_id] = []
    await update.message.reply_text("تاریخچه مکالمه پاک شد.")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
