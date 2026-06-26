import os
import json
import logging
import asyncio
from datetime import datetime
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
import google.generativeai as genai

# ========== تنظیمات ==========
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

# ========== چندین API Key ==========
API_KEYS = []
for i in range(1, 6):
    key = os.environ.get(f"GEMINI_API_KEY_{i}")
    if key:
        API_KEYS.append(key)

if not API_KEYS:
    # اگه کلیدهای جدید نبود، از کلید اصلی استفاده کن
    main_key = os.environ.get("GEMINI_API_KEY")
    if main_key:
        API_KEYS.append(main_key)

if not API_KEYS:
    logger.error("❌ هیچ API Key ای تنظیم نشده!")
    exit(1)

if not TELEGRAM_TOKEN or not OWNER_ID:
    logger.error("❌ TELEGRAM_TOKEN یا OWNER_ID تنظیم نشده!")
    exit(1)

# ========== مدل ==========
MODEL_NAME = "gemini-1.5-flash"  # ✅ مدل مطمئن‌تر

# ========== پرامپت ==========
SYSTEM_PROMPT = """تو یک دستیار هوشمند هستی که قراره به جای صاحبش صحبت کنی.

دستورالعمل‌ها:
۱. مثل یک انسان معمولی و خودمانی صحبت کن
۲. فقط به فارسی جواب بده
۳. از کلمات محاوره‌ای و صمیمی استفاده کن
۴. اگر چیزی نمی‌دونی، بگو "نمیدونم"
۵. هرگز نگو "من یک ربات هستم"
۶. پاسخ‌هات کوتاه و مختصر باشه"""

# ========== پیدا کردن کلید کاری (ساده‌شده) ==========
current_key_index = 0

def get_next_key():
    """گرفتن کلید بعدی به صورت چرخشی"""
    global current_key_index
    key = API_KEYS[current_key_index]
    current_key_index = (current_key_index + 1) % len(API_KEYS)
    return key

# ========== محدودیت کاربران ==========
user_message_count = {}
DAILY_LIMIT = 100

async def check_limit(user_id):
    if user_id == OWNER_ID:
        return True
    
    today = datetime.now().date()
    if user_id not in user_message_count:
        user_message_count[user_id] = {"count": 0, "date": today}
    
    if user_message_count[user_id]["date"] != today:
        user_message_count[user_id] = {"count": 0, "date": today}
    
    if user_message_count[user_id]["count"] >= DAILY_LIMIT:
        return False
    
    user_message_count[user_id]["count"] += 1
    return True

# ========== تاریخچه ==========
conversation_history = {}
pending_questions = {}

HARD_QUESTIONS = ["حل کن", "راهنمایی کن", "نظریه", "برنامه", "کد", "پروژه", "تحلیل", "پژوهش", "مقاله", "ترجمه", "تخصصی", "پیشرفته", "الگوریتم", "ریاضی", "فیزیک", "شیمی", "برنامه‌نویسی"]

def is_hard_question(text):
    text = text.lower()
    for keyword in HARD_QUESTIONS:
        if keyword in text:
            return True
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_name = user.first_name or "کاربر"
    
    await update.message.reply_text(
        f"👋 سلام {user_name}!\n\n"
        f"من دستیار هوشمند هستم.\n"
        f"هر سوالی داری، بپرس! 🤖\n\n"
        f"📊 سهمیه روزانه: {DAILY_LIMIT} پیام\n"
        f"🔑 تعداد کلیدها: {len(API_KEYS)}\n"
        f"🔧 مدل: {MODEL_NAME}"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    user_name = user.first_name or "کاربر"
    user_text = update.message.text
    chat_id = update.effective_chat.id

    # ========== بررسی محدودیت ==========
    if not await check_limit(user_id):
        await update.message.reply_text(
            f"⛔ شما امروز {DAILY_LIMIT} پیام استفاده کردید.\n"
            f"لطفاً فردا دوباره تلاش کنید. 🌙"
        )
        return

    # ========== چک کردن سوال سخت ==========
    if is_hard_question(user_text):
        try:
            username = user.username or "بدون یوزرنیم"
            
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=f"🔔 **سوال از {user_name}**\n"
                     f"👤 @{username}\n"
                     f"🆔 `{user_id}`\n\n"
                     f"**سوال:**\n{user_text}"
            )
            
            pending_questions[user_id] = {
                "question": user_text,
                "chat_id": chat_id,
                "user_name": user_name
            }
            
            await update.message.reply_text(
                f"🔍 سوال شما به صاحبم فرستاده شد!\n"
                f"⏳ اگه ۵ دقیقه جواب ندم، خودم پاسخ می‌دم."
            )
            
            asyncio.create_task(auto_reply_after_timeout(user_id, context))
            return
            
        except Exception as e:
            logger.error(f"❌ خطا: {e}")

    # ========== پاسخ معمولی ==========
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
        
        # ========== استفاده از کلید بعدی ==========
        key = get_next_key()
        genai.configure(api_key=key)
        
        model = genai.GenerativeModel(
            model_name=MODEL_NAME,
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
        error_msg = str(e)
        
        if "quota" in error_msg.lower() or "429" in error_msg:
            await update.message.reply_text(
                f"❌ سهمیه API تموم شده!\n"
                f"لطفاً بعداً تلاش کن. ⏳"
            )
        elif "invalid" in error_msg.lower() or "key" in error_msg.lower():
            await update.message.reply_text(
                f"❌ کلید API نامعتبر!\n"
                f"لطفاً کلیدها رو چک کن."
            )
        else:
            await update.message.reply_text(f"❌ خطا: {error_msg[:100]}")

async def auto_reply_after_timeout(user_id, context):
    await asyncio.sleep(300)
    
    if user_id not in pending_questions:
        return
    
    data = pending_questions[user_id]
    chat_id = data["chat_id"]
    question = data["question"]
    
    del pending_questions[user_id]
    
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⏰ ۵ دقیقه گذشت! خودم پاسخ می‌دم. 🤖"
        )
        
        key = get_next_key()
        genai.configure(api_key=key)
        
        model = genai.GenerativeModel(
            model_name=MODEL_NAME,
            system_instruction=SYSTEM_PROMPT
        )
        
        response = model.generate_content(question)
        reply = response.text
        
        await context.bot.send_message(chat_id=chat_id, text=reply)
        
    except Exception as e:
        logger.error(f"❌ خطا: {e}")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("⛔ فقط مالک.")
        return
    
    await update.message.reply_text(
        f"📊 **وضعیت ربات:**\n\n"
        f"🔑 تعداد کلیدها: {len(API_KEYS)}\n"
        f"💾 مکالمات: {len(conversation_history)}\n"
        f"👤 کاربران امروز: {len(user_message_count)}\n"
        f"📊 محدودیت روزانه: {DAILY_LIMIT} پیام\n"
        f"🔧 مدل: {MODEL_NAME}"
    )

async def reset_quota(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    
    global user_message_count
    user_message_count = {}
    await update.message.reply_text("✅ سهمیه همه کاربران ریست شد!")

async def add_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    
    if not context.args:
        await update.message.reply_text("❌ کلید رو وارد کن: /add_key AIzaSy...")
        return
    
    new_key = context.args[0]
    API_KEYS.append(new_key)
    await update.message.reply_text(f"✅ کلید جدید اضافه شد! (مجموع: {len(API_KEYS)})")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("reset_quota", reset_quota))
    app.add_handler(CommandHandler("add_key", add_key))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("🚀 ربات روشن شد!")
    logger.info(f"👤 مالک: {OWNER_ID}")
    logger.info(f"🔑 تعداد کلیدها: {len(API_KEYS)}")
    logger.info(f"🔧 مدل: {MODEL_NAME}")
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
