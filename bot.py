import os
import json
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler  # ✅ CommandHandler اضافه شد
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

# ========== بارگذاری فایل JSON (اگه باشه) ==========
chat_context = ""
json_loaded = False
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
                        sender = msg.get("from", "")
                        messages_list.append(f"{sender}: {text.strip()}")
        elif "messages" in data:
            for msg in data.get("messages", []):
                text = msg.get("text")
                if isinstance(text, str) and text.strip():
                    sender = msg.get("from", "")
                    messages_list.append(f"{sender}: {text.strip()}")
        
        if messages_list:
            recent = messages_list[-300:]
            chat_context = "\n".join(recent)
            json_loaded = True
            logger.info(f"✅ {len(recent)} پیام از JSON بارگذاری شد")
        else:
            logger.warning("⚠️ فایل JSON پیدا شد ولی پیامی توش نبود!")
            
    except Exception as e:
        logger.error(f"❌ خطا در بارگذاری JSON: {e}")
else:
    logger.warning("⚠️ فایل JSON پیدا نشد!")

# ========== ساخت پرامپت هوشمند ==========
def build_prompt():
    if json_loaded and chat_context:
        return f"""تو دقیقاً مثل صاحب این اکانت تلگرام جواب بده.

تاریخچه چت‌های اخیر این شخص (از فایل JSON):
{chat_context}

قوانین مهم:
۱. دقیقاً مثل این شخص صحبت کن (همون لحن، کلمات، و سبک)
۲. از کلمات و اصطلاحات تکراری این شخص استفاده کن
۳. مثل یک انسان معمولی جواب بده، نه ربات
۴. فقط فارسی جواب بده
۵. هیچوقت نگو "من یک ربات هستم"
۶. اگه چیزی نمی‌دونی، بگو "نمیدونم"
"""
    else:
        return """تو یک دستیار هوشمند هستی که قراره به جای صاحبش صحبت کنی.

دستورالعمل‌ها:
۱. مثل یک انسان معمولی و خودمانی صحبت کن
۲. فقط به فارسی جواب بده
۳. از کلمات محاوره‌ای و صمیمی استفاده کن
۴. اگر چیزی نمی‌دونی، بگو "نمیدونم" یا "والا نمی‌دونم"
۵. هرگز نگو "من یک ربات هستم" یا "به عنوان هوش مصنوعی"
۶. پاسخ‌هات کوتاه و مختصر باشه (حداکثر ۲-۳ خط)
۷. با اعتماد به نفس و طبیعی صحبت کن

مهم: تو داری به جای یک شخص واقعی صحبت می‌کنی، پس کاملاً طبیعی و انسانی جواب بده."""

SYSTEM_PROMPT = build_prompt()

# ========== تاریخچه مکالمه ==========
conversation_history = {}

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if AUTHORIZED_USER_ID and user_id != AUTHORIZED_USER_ID:
        await update.message.reply_text("⛔ دسترسی مجاز نیست.")
        return

    user_text = update.message.text
    chat_id = update.effective_chat.id

    if chat_id not in conversation_history:
        conversation_history[chat_id] = []
    
    conversation_history[chat_id].append({
        "role": "user",
        "parts": [user_text]
    })
    
    if len(conversation_history[chat_id]) > 30:
        conversation_history[chat_id] = conversation_history[chat_id][-30:]

    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            system_instruction=SYSTEM_PROMPT
        )
        
        chat = model.start_chat(history=conversation_history[chat_id][:-1])
        response = chat.send_message(user_text)
        reply = response.text
        
        conversation_history[chat_id].append({
            "role": "model",
            "parts": [reply]
        })
        
        await update.message.reply_text(reply)
        
    except Exception as e:
        logger.error(f"❌ خطا: {e}")
        await update.message.reply_text("❌ یه مشکلی پیش اومد! دوباره امتحان کن.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /status - نمایش وضعیت"""
    user_id = update.effective_user.id
    if AUTHORIZED_USER_ID and user_id != AUTHORIZED_USER_ID:
        await update.message.reply_text("⛔ دسترسی مجاز نیست.")
        return
    
    status_text = f"""📊 **وضعیت ربات:**

📁 **فایل JSON:** {'✅ موجود' if json_loaded else '❌ موجود نیست'}
📝 **تعداد پیام‌ها:** {len(chat_context.split(chr(10))) if chat_context else 0}
🤖 **حالت فعلی:** {'یادگیری از JSON' if json_loaded else 'حالت عادی (بدون JSON)'}

💡 ربات با هر پیام شما بیشتر یاد می‌گیره!
"""
    await update.message.reply_text(status_text)

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # هندلرها
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CommandHandler("status", status))  # ✅ الان درست کار میکنه
    
    logger.info("🚀 ربات هوشمند روشن شد!")
    logger.info(f"📁 وضعیت JSON: {'✅ بارگذاری شد' if json_loaded else '❌ وجود نداره یا خالی'}")
    logger.info(f"👤 کاربر مجاز: {AUTHORIZED_USER_ID}")
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
