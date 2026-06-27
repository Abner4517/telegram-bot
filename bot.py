import os
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import google.generativeai as genai

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")  # فقط یک کلید ساده
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    logger.error("❌ متغیرها تنظیم نشده!")
    exit(1)

genai.configure(api_key=GEMINI_API_KEY)

SYSTEM_PROMPT = """تو یک دستیار هستی که به جای صاحبش صحبت می‌کنی.
پاسخ‌هات کوتاه، خودمونی و فارسی باشه.
هیچوقت نگو ربات هستم."""

conversation_history = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 سلام! من حسن کوچولو هستم! هر سوالی بپرس.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    user_text = update.message.text

    if user_id != OWNER_ID:
        # به غیر از خودت، به بقیه جواب بده
        pass

    if chat_id not in conversation_history:
        conversation_history[chat_id] = []

    conversation_history[chat_id].append({"role": "user", "parts": [user_text]})
    if len(conversation_history[chat_id]) > 30:
        conversation_history[chat_id] = conversation_history[chat_id][-30:]

    try:
        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash-lite",  # ✅ مدل سبک و رایگان
            system_instruction=SYSTEM_PROMPT
        )
        chat = model.start_chat(history=conversation_history[chat_id][:-1])
        response = chat.send_message(user_text)
        reply = response.text

        conversation_history[chat_id].append({"role": "model", "parts": [reply]})
        await update.message.reply_text(reply)

    except Exception as e:
        logger.error(f"❌ خطا: {e}")
        await update.message.reply_text("❌ خطا! دوباره تلاش کن.")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("🚀 ربات روشن شد!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
