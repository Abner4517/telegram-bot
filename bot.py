import os
import json
import logging
import asyncio
import hashlib
from datetime import datetime, timedelta
from collections import deque
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler, CallbackQueryHandler
import google.generativeai as genai

# ========== تنظیمات ==========
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

# ========== چندین API Key ==========
API_KEYS = [
    os.environ.get("GEMINI_API_KEY_1"),
    os.environ.get("GEMINI_API_KEY_2"),
    os.environ.get("GEMINI_API_KEY_3"),
]

API_KEYS = [key for key in API_KEYS if key]

if not API_KEYS:
    logger.error("❌ هیچ API Key ای تنظیم نشده!")
    exit(1)

if not TELEGRAM_TOKEN or not OWNER_ID:
    logger.error("❌ TELEGRAM_TOKEN یا OWNER_ID تنظیم نشده!")
    exit(1)

# ========== مدیریت کلیدها ==========
current_key_index = 0

def get_next_key():
    global current_key_index
    current_key_index = (current_key_index + 1) % len(API_KEYS)
    return API_KEYS[current_key_index]

def get_working_key():
    for key in API_KEYS:
        try:
            genai.configure(api_key=key)
            test_model = genai.GenerativeModel("gemini-1.5-flash")
            test_response = test_model.generate_content("سلام")
            return key
        except Exception as e:
            logger.warning(f"⚠️ کلید {key[:10]}... کار نمیکنه: {e}")
            continue
    return None

# ========== کش کردن پاسخ‌ها ==========
cache = {}
CACHE_DURATION = 3600

def get_cached_response(question):
    q_hash = hashlib.md5(question.encode()).hexdigest()
    if q_hash in cache:
        data = cache[q_hash]
        if datetime.now() - data["time"] < timedelta(seconds=CACHE_DURATION):
            return data["answer"]
    return None

def save_to_cache(question, answer):
    q_hash = hashlib.md5(question.encode()).hexdigest()
    cache[q_hash] = {"answer": answer, "time": datetime.now()}

# ========== صف درخواست‌ها ==========
request_queue = deque()
is_processing = False
MAX_CONCURRENT = 5

async def process_queue():
    global is_processing
    if is_processing or not request_queue:
        return
    
    is_processing = True
    try:
        while request_queue:
            batch = []
            for _ in range(min(MAX_CONCURRENT, len(request_queue))):
                if request_queue:
                    batch.append(request_queue.popleft())
            
            tasks = []
            for item in batch:
                tasks.append(process_request(item))
            
            await asyncio.gather(*tasks)
            await asyncio.sleep(1)
    finally:
        is_processing = False

async def process_request(item):
    try:
        update, user_text, chat_id, reply_to_user = item
        
        cached = get_cached_response(user_text)
        if cached:
            await reply_to_user(cached)
            return
        
        key = get_working_key()
        if not key:
            await reply_to_user("❌ همه کلیدهای API تموم شدن! لطفاً بعداً تلاش کن.")
            return
        
        genai.configure(api_key=key)
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            system_instruction=SYSTEM_PROMPT
        )
        
        response = model.generate_content(user_text)
        reply = response.text
        
        save_to_cache(user_text, reply)
        await reply_to_user(reply)
        
    except Exception as e:
        logger.error(f"❌ خطا: {e}")
        await reply_to_user(f"❌ خطا: {str(e)[:100]}")

# ========== پرامپت ==========
SYSTEM_PROMPT = """تو یک دستیار هوشمند هستی که قراره به جای صاحبش صحبت کنی.

دستورالعمل‌ها:
۱. مثل یک انسان معمولی و خودمانی صحبت کن
۲. فقط به فارسی جواب بده
۳. از کلمات محاوره‌ای و صمیمی استفاده کن
۴. اگر چیزی نمی‌دونی، بگو "نمیدونم" یا "والا نمی‌دونم"
۵. هرگز نگو "من یک ربات هستم"
۶. پاسخ‌هات کوتاه و مختصر باشه (حداکثر ۲-۳ خط)"""

# ========== محدودیت کاربران ==========
user_message_count = {}
DAILY_LIMIT = 100  # ✅ هر کاربر روزانه ۱۰۰ پیام

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
        f"💾 کش: فعال (۱ ساعت)"
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
    request_queue.append((update, user_text, chat_id, update.message.reply_text))
    asyncio.create_task(process_queue())

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
        
        cached = get_cached_response(question)
        if cached:
            await context.bot.send_message(chat_id=chat_id, text=cached)
            return
        
        key = get_working_key()
        if not key:
            await context.bot.send_message(chat_id=chat_id, text="❌ خطا! لطفاً بعداً تلاش کن.")
            return
        
        genai.configure(api_key=key)
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            system_instruction=SYSTEM_PROMPT
        )
        
        response = model.generate_content(question)
        reply = response.text
        
        save_to_cache(question, reply)
        await context.bot.send_message(chat_id=chat_id, text=reply)
        
    except Exception as e:
        logger.error(f"❌ خطا: {e}")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("⛔ فقط مالک.")
        return
    
    await update.message.reply_text(
        f"📊 **وضعیت ربات:**\n\n"
        f"🔑 کلیدهای API: {len(API_KEYS)}\n"
        f"💾 کش: {len(cache)} آیتم\n"
        f"⏳ صف: {len(request_queue)} درخواست\n"
        f"👤 کاربران امروز: {len(user_message_count)}\n"
        f"📊 محدودیت روزانه: {DAILY_LIMIT} پیام"
    )

async def clear_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    
    global cache
    cache = {}
    await update.message.reply_text("✅ کش پاک شد!")

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

async def set_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /set_limit <number> - تغییر محدودیت روزانه"""
    if update.effective_user.id != OWNER_ID:
        return
    
    if not context.args:
        await update.message.reply_text("❌ عدد رو وارد کن: /set_limit 100")
        return
    
    try:
        new_limit = int(context.args[0])
        global DAILY_LIMIT
        DAILY_LIMIT = new_limit
        await update.message.reply_text(f"✅ محدودیت روزانه به {DAILY_LIMIT} پیام تغییر کرد!")
    except ValueError:
        await update.message.reply_text("❌ لطفاً یک عدد معتبر وارد کن.")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("clear_cache", clear_cache))
    app.add_handler(CommandHandler("reset_quota", reset_quota))
    app.add_handler(CommandHandler("add_key", add_key))
    app.add_handler(CommandHandler("set_limit", set_limit))  # ✅ دستور جدید
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("🚀 ربات هوشمند روشن شد!")
    logger.info(f"👤 مالک: {OWNER_ID}")
    logger.info(f"🔑 تعداد کلیدها: {len(API_KEYS)}")
    logger.info(f"📊 محدودیت روزانه: {DAILY_LIMIT} پیام")
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
