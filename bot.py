import os
import json
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
import google.generativeai as genai

# ========== تنظیمات ==========
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")  # ✅ درست شد
AUTHORIZED_USER_ID = int(os.environ.get("AUTHORIZED_USER_ID", "0"))

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    logger.error("❌ TELEGRAM_TOKEN یا GEMINI_API_KEY تنظیم نشده!")
    exit(1)

# ========== تنظیم Gemini ==========
try:
    genai.configure(api_key=GEMINI_API_KEY)
    logger.info("✅ Gemini API تنظیم شد")
except Exception as e:
    logger.error(f"❌ خطا: {e}")
    exit(1)

# ========== بارگذاری فایل JSON ==========
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

# ========== پرامپت ==========
def build_prompt():
    if json_loaded and chat_context:
        # کوتاه کردن پرامپت
        context_preview = chat_context[:2000] + "..." if len(chat_context) > 2000 else chat_context
        
        return f"""تو مثل این شخص صحبت کن.

تاریخچه (خلاصه):
{context_preview}

قوانین:
۱. مثل این شخص صحبت کن
۲. فارسی جواب بده
۳. مثل انسان باش
"""
    else:
        return """تو یک انسان معمولی هستی که به فارسی صحبت می‌کنی.
قوانین:
- مثل یک انسان معمولی و خودمانی صحبت کن
- فقط فارسی جواب بده
- کوتاه و مختصر جواب بده
- هیچوقت نگو ربات هستم"""

SYSTEM_PROMPT = build_prompt()
logger.info(f"✅ پرامپت ساخته شد (طول: {len(SYSTEM_PROMPT)} کاراکتر)")

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
        await update.message.reply_text(f"❌ خطا: {str(e)[:100]}")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if AUTHORIZED_USER_ID and user_id != AUTHORIZED_USER_ID:
        await update.message.reply_text("⛔ دسترسی مجاز نیست.")
        return
    
    status_text = f"""📊 **وضعیت ربات:**

📁 **فایل JSON:** {'✅ موجود' if json_loaded else '❌ موجود نیست'}
📝 **تعداد پیام‌ها:** {len(chat_context.split(chr(10))) if chat_context else 0}
🤖 **Gemini API:** {'✅ متصل' if GEMINI_API_KEY else '❌'}
📝 **طول پرامپت:** {len(SYSTEM_PROMPT)} کاراکتر

💡 ربات با هر پیام شما بیشتر یاد می‌گیره!
"""
    await update.message.reply_text(status_text)

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if AUTHORIZED_USER_ID and user_id != AUTHORIZED_USER_ID:
        return
    chat_id = update.effective_chat.id
    conversation_history[chat_id] = []
    await update.message.reply_text("🔄 تاریخچه پاک شد!")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("reset", reset))
    
    logger.info("🚀 ربات هوشمند روشن شد!")
    logger.info(f"📁 وضعیت JSON: {'✅' if json_loaded else '❌'}")
    logger.info(f"👤 کاربر مجاز: {AUTHORIZED_USER_ID}")
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
