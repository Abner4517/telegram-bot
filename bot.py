import os
import json
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
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

# ========== بارگذاری تاریخچه ==========
chat_context = ""
export_path = "telegram_export.json"

if os.path.exists(export_path):
    try:
        with open(export_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        messages_list = []
        
        # استخراج پیام‌ها
        if "chats" in data:
            for chat in data["chats"].get("list", []):
                for msg in chat.get("messages", []):
                    text = msg.get("text")
                    if isinstance(text, str) and text.strip():
                        sender = msg.get("from", "نامشخص")
                        messages_list.append(f"{sender}: {text.strip()}")
        elif "messages" in data:
            for msg in data.get("messages", []):
                text = msg.get("text")
                if isinstance(text, str) and text.strip():
                    sender = msg.get("from", "نامشخص")
                    messages_list.append(f"{sender}: {text.strip()}")
        
        if messages_list:
            recent = messages_list[-300:]
            chat_context = "\n".join(recent)
            logger.info(f"✅ {len(recent)} پیام بارگذاری شد")
    except Exception as e:
        logger.error(f"❌ خطا: {e}")
else:
    logger.warning("⚠️ telegram_export.json پیدا نشد!")

# ========== پرامپت ==========
SYSTEM_PROMPT = f"""تو دقیقاً مثل صاحب این اکانت تلگرام جواب بده.

تاریخچه چت‌های اخیر:
{chat_context if chat_context else "تاریخچه‌ای موجود نیست"}

قوانین:
۱. دقیقاً مثل این شخص صحبت کن (همون لحن، کلمات، و سبک)
۲. مثل یک انسان معمولی جواب بده، نه ربات
۳. فقط فارسی جواب بده
۴. هرگز نگو "من یک ربات هستم" یا "به عنوان هوش مصنوعی"
۵. اگه چیزی نمی‌دونی، بگو "نمیدونم" یا "والا نمی‌دونم"
"""

conversation_history = {}

# ========== هندلر پیام ==========
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # فقط کاربر مجاز می‌تونه استفاده کنه
    if AUTHORIZED_USER_ID and user_id != AUTHORIZED_USER_ID:
        await update.message.reply_text("⛔ دسترسی مجاز نیست.")
        return

    user_text = update.message.text
    chat_id = update.effective_chat.id

    # مدیریت تاریخچه
    if chat_id not in conversation_history:
        conversation_history[chat_id] = []
    
    conversation_history[chat_id].append({"role": "user", "parts": [user_text]})
    
    if len(conversation_history[chat_id]) > 50:
        conversation_history[chat_id] = conversation_history[chat_id][-50:]

    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        
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
        await update.message.reply_text("❌ یه مشکلی پیش اومد!")

# ========== اجرا ==========
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # فقط هندلر پیام - بدون هیچ دستوری
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("🚀 ربات شخصیت‌ساز روشن شد!")
    logger.info(f"👤 کاربر مجاز: {AUTHORIZED_USER_ID}")
    logger.info(f"📊 تاریخچه: {'✅' if chat_context else '❌'}")
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
