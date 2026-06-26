import os
import json
import logging
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
import google.generativeai as genai

# ========== تنظیمات ==========
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
AUTHORIZED_USER_ID = int(os.environ.get("AUTHORIZED_USER_ID", "0"))

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    logger.error("❌ متغیرهای محیطی تنظیم نشده!")
    exit(1)

genai.configure(api_key=GEMINI_API_KEY)

# ========== پرامپت ==========
SYSTEM_PROMPT = """تو قراره به جای صاحب این اکانت جواب بدی.
- دقیقاً مثل یک انسان معمولی صحبت کن
- فقط فارسی جواب بده
- کوتاه و مختصر جواب بده (حداکثر ۲-۳ خط)
- با لحن خودمونی و دوستانه
- هیچوقت نگو ربات هستم یا هوش مصنوعی هستم"""

conversation_history = {}

# ========== ساخت اپلیکیشن ==========
app_telegram = Application.builder().token(TELEGRAM_TOKEN).build()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # اگه خودت پیام دادی، نادیده بگیر (تا ربات به خودت جواب نده)
    if user_id == AUTHORIZED_USER_ID:
        return

    user_text = update.message.text
    chat_id = update.effective_chat.id

    if chat_id not in conversation_history:
        conversation_history[chat_id] = []
    
    conversation_history[chat_id].append({"role": "user", "parts": [user_text]})
    
    if len(conversation_history[chat_id]) > 30:
        conversation_history[chat_id] = conversation_history[chat_id][-30:]

    try:
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
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

# هندلرها
app_telegram.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# ========== Flask برای Webhook ==========
flask_app = Flask(__name__)

@flask_app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update = Update.de_json(request.get_json(), app_telegram.bot)
        app_telegram.process_update(update)
        return 'OK', 200
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return 'Error', 500

@flask_app.route('/')
def home():
    return "ربات روشن است! ✅"

# ========== اجرا ==========
if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 8080))
    
    # تنظیم Webhook
    WEBHOOK_URL = f"https://{os.environ.get('RAILWAY_STATIC_URL')}/webhook"
    
    try:
        app_telegram.bot.set_webhook(WEBHOOK_URL)
        logger.info(f"✅ Webhook تنظیم شد: {WEBHOOK_URL}")
    except Exception as e:
        logger.error(f"❌ خطا در تنظیم Webhook: {e}")
    
    logger.info("🚀 ربات Business روشن شد!")
    flask_app.run(host="0.0.0.0", port=PORT)
