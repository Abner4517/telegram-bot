import os
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
import google.generativeai as genai

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    logger.error("❌ متغیرها تنظیم نشده!")
    exit(1)

# ========== تنظیم Gemini با خطایابی ==========
try:
    genai.configure(api_key=GEMINI_API_KEY)
    logger.info("✅ Gemini تنظیم شد")
    
    # تست اتصال
    test_model = genai.GenerativeModel("gemini-2.0-flash-lite")
    test_response = test_model.generate_content("سلام")
    logger.info(f"✅ تست Gemini موفق: {test_response.text[:20]}...")
    
except Exception as e:
    logger.error(f"❌ خطا در تنظیم Gemini: {e}")
    exit(1)

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

    if chat_id not in conversation_history:
        conversation_history[chat_id] = []

    conversation_history[chat_id].append({"role": "user", "parts": [user_text]})
    if len(conversation_history[chat_id]) > 30:
        conversation_history[chat_id] = conversation_history[chat_id][-30:]

    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        
        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash-lite",
            system_instruction=SYSTEM_PROMPT
        )
        chat = model.start_chat(history=conversation_history[chat_id][:-1])
        response = chat.send_message(user_text)
        reply = response.text

        conversation_history[chat_id].append({"role": "model", "parts": [reply]})
        await update.message.reply_text(reply)

    except Exception as e:
        logger.error(f"❌ خطای کامل: {e}")
        error_msg = str(e)
        
        if "quota" in error_msg.lower() or "429" in error_msg:
            await update.message.reply_text(
                "❌ سهمیه امروز تموم شده!\n"
                "لطفاً فردا دوباره تلاش کن. 🌙\n"
                "یا با یه کلید جدید امتحان کن."
            )
        elif "invalid" in error_msg.lower() or "key" in error_msg.lower():
            await update.message.reply_text(
                "❌ کلید API نامعتبر!\n"
                "لطفاً کلید رو چک کن."
            )
        elif "not found" in error_msg.lower() or "404" in error_msg:
            await update.message.reply_text(
                "❌ مدل در دسترس نیست!\n"
                "لطفاً به صاحبم اطلاع بده. 🔧"
            )
        else:
            await update.message.reply_text(f"❌ خطا: {error_msg[:150]}")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /status - وضعیت ربات"""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("⛔ فقط مالک.")
        return
    
    # تست کلید
    try:
        test_model = genai.GenerativeModel("gemini-2.0-flash-lite")
        test_response = test_model.generate_content("سلام")
        api_status = "✅ سالم"
    except Exception as e:
        api_status = f"❌ خطا: {str(e)[:50]}"
    
    await update.message.reply_text(
        f"📊 **وضعیت ربات:**\n\n"
        f"🔑 API: {api_status}\n"
        f"💾 مکالمات: {len(conversation_history)}\n"
        f"🔧 مدل: gemini-2.0-flash-lite"
    )

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("🚀 ربات روشن شد!")
    logger.info(f"👤 مالک: {OWNER_ID}")
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
