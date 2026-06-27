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

genai.configure(api_key=GEMINI_API_KEY)

# ========== لیست مدل‌ها ==========
MODELS = [
    "gemini-1.5-flash",
    "gemini-pro",
    "gemini-1.0-pro",
]

# پیدا کردن مدل موجود
MODEL_NAME = None
for model in MODELS:
    try:
        test = genai.GenerativeModel(model)
        test.generate_content("سلام")
        MODEL_NAME = model
        logger.info(f"✅ مدل {model} در دسترس است")
        break
    except Exception as e:
        logger.warning(f"⚠️ مدل {model} در دسترس نیست: {e}")

if not MODEL_NAME:
    MODEL_NAME = "gemini-1.5-flash"
    logger.warning(f"⚠️ استفاده از پیش‌فرض: {MODEL_NAME}")

SYSTEM_PROMPT = """تو یک دستیار هستی که به جای صاحبش صحبت می‌کنی.
پاسخ‌هات کوتاه، خودمونی و فارسی باشه.
هیچوقت نگو ربات هستم."""

conversation_history = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"👋 سلام! من حسن کوچولو هستم! 😊\n"
        f"هر سوالی بپرس.\n"
        f"🔧 مدل: {MODEL_NAME}"
    )

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
            model_name=MODEL_NAME,
            system_instruction=SYSTEM_PROMPT
        )
        chat = model.start_chat(history=conversation_history[chat_id][:-1])
        response = chat.send_message(user_text)
        reply = response.text

        conversation_history[chat_id].append({"role": "model", "parts": [reply]})
        await update.message.reply_text(reply)

    except Exception as e:
        logger.error(f"❌ خطا: {e}")
        error_msg = str(e)
        
        if "quota" in error_msg.lower() or "429" in error_msg:
            await update.message.reply_text(
                f"❌ سهمیه مدل {MODEL_NAME} تموم شده!\n"
                f"لطفاً چند دقیقه صبر کن یا با /switch_model مدل دیگه رو امتحان کن."
            )
        else:
            await update.message.reply_text(f"❌ خطا: {error_msg[:100]}")

async def switch_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /switch_model - تغییر مدل"""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("⛔ فقط مالک.")
        return
    
    global MODEL_NAME
    current_index = MODELS.index(MODEL_NAME) if MODEL_NAME in MODELS else 0
    next_index = (current_index + 1) % len(MODELS)
    MODEL_NAME = MODELS[next_index]
    
    await update.message.reply_text(f"✅ مدل تغییر کرد به: {MODEL_NAME}")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("⛔ فقط مالک.")
        return
    
    await update.message.reply_text(
        f"📊 **وضعیت ربات:**\n\n"
        f"🔧 مدل فعلی: {MODEL_NAME}\n"
        f"📋 مدل‌های موجود: {', '.join(MODELS)}\n"
        f"💾 مکالمات: {len(conversation_history)}"
    )

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("switch_model", switch_model))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("🚀 ربات روشن شد!")
    logger.info(f"🔧 مدل: {MODEL_NAME}")
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
