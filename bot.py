import os
import json
import logging
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler, CallbackQueryHandler
import google.generativeai as genai

# ========== تنظیمات ==========
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

if not TELEGRAM_TOKEN or not GEMINI_API_KEY or not OWNER_ID:
    logger.error("❌ متغیرهای محیطی تنظیم نشده!")
    exit(1)

genai.configure(api_key=GEMINI_API_KEY)

# ========== انتخاب مدل درست ==========
MODEL_NAME = "gemini-1.5-flash"  # ✅ مدل مطمئن‌تر

# تست مدل
try:
    test_model = genai.GenerativeModel(MODEL_NAME)
    test_response = test_model.generate_content("سلام")
    logger.info(f"✅ مدل {MODEL_NAME} در دسترس است")
except Exception as e:
    logger.error(f"❌ مدل {MODEL_NAME} در دسترس نیست: {e}")
    # استفاده از مدل جایگزین
    MODEL_NAME = "gemini-2.0-flash"
    logger.info(f"🔄 استفاده از مدل جایگزین: {MODEL_NAME}")

# ========== پرامپت ==========
SYSTEM_PROMPT = """تو یک دستیار هوشمند هستی که قراره به جای صاحبش صحبت کنی.

دستورالعمل‌ها:
۱. مثل یک انسان معمولی و خودمانی صحبت کن
۲. فقط به فارسی جواب بده
۳. از کلمات محاوره‌ای و صمیمی استفاده کن
۴. اگر چیزی نمی‌دونی، بگو "نمیدونم" یا "والا نمی‌دونم"
۵. هرگز نگو "من یک ربات هستم" یا "به عنوان هوش مصنوعی"
۶. پاسخ‌هات کوتاه و مختصر باشه (حداکثر ۲-۳ خط)
۷. با اعتماد به نفس و طبیعی صحبت کن"""

# ========== تاریخچه ==========
conversation_history = {}
pending_questions = {}  # {user_id: {"question": text, "chat_id": id, "time": datetime}}

# کلمات کلیدی برای تشخیص سوالات سخت
HARD_QUESTIONS = [
    "حل کن", "راهنمایی کن", "نظریه", "برنامه", "کد", "پروژه",
    "تحلیل", "پژوهش", "مقاله", "ترجمه", "تخصصی", "پیشرفته",
    "الگوریتم", "ریاضی", "فیزیک", "شیمی", "برنامه‌نویسی"
]

def is_hard_question(text):
    """تشخیص سوال سخت"""
    text = text.lower()
    for keyword in HARD_QUESTIONS:
        if keyword in text:
            return True
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /start"""
    user = update.effective_user
    user_name = user.first_name or "کاربر"
    
    await update.message.reply_text(
        f"👋 سلام {user_name}!\n\n"
        f"من دستیار هوشمند هستم که به جای صاحبش صحبت می‌کنم.\n"
        f"هر سوالی داری، بپرس! 🤖\n\n"
        f"ℹ️ اگه سوال شما تخصصی باشه، پیامت رو به صاحبم می‌فرستم.\n"
        f"اگه ۵ دقیقه جواب ندم، خودم بهت پاسخ می‌دم.\n\n"
        f"🔧 مدل: {MODEL_NAME}"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت پیام‌ها"""
    user = update.effective_user
    user_id = user.id
    user_name = user.first_name or "کاربر"
    username = user.username or "بدون یوزرنیم"
    user_text = update.message.text
    chat_id = update.effective_chat.id

    # ========== چک کردن سوال سخت ==========
    if is_hard_question(user_text):
        try:
            forward_msg = (
                f"🔔 **سوال سخت از {user_name}**\n"
                f"👤 یوزرنیم: @{username}\n"
                f"🆔 آیدی: `{user_id}`\n\n"
                f"**سوال:**\n{user_text}\n\n"
                f"⏳ شما ۵ دقیقه وقت دارید."
            )
            
            keyboard = [
                [
                    InlineKeyboardButton("✅ پاسخ خودم", callback_data=f"answer_{chat_id}_{user_id}"),
                    InlineKeyboardButton("🤖 بذار ربات جواب بده", callback_data=f"robot_{chat_id}_{user_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=forward_msg,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            
            pending_questions[user_id] = {
                "question": user_text,
                "chat_id": chat_id,
                "user_id": user_id,
                "user_name": user_name,
                "time": datetime.now()
            }
            
            await update.message.reply_text(
                f"🔍 سوال شما تخصصی به نظر میرسه!\n"
                f"من پیامت رو برای صاحبم فرستادم. ⏳\n\n"
                f"⏱️ اگه ۵ دقیقه جواب ندم، خودم بهت پاسخ می‌دم."
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
        await update.message.reply_text(
            f"❌ خطا: {str(e)[:100]}\n"
            f"لطفاً دوباره تلاش کن."
        )

async def auto_reply_after_timeout(user_id, context):
    """پاسخ خودکار بعد از ۵ دقیقه"""
    await asyncio.sleep(300)
    
    if user_id not in pending_questions:
        return
    
    data = pending_questions[user_id]
    chat_id = data["chat_id"]
    question = data["question"]
    user_name = data["user_name"]
    
    del pending_questions[user_id]
    
    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⏰ ۵ دقیقه گذشت و صاحبم جواب نداد.\n"
                 f"خودم به سوال شما پاسخ می‌دم. 🤖"
        )
        
        model = genai.GenerativeModel(
            model_name=MODEL_NAME,
            system_instruction=SYSTEM_PROMPT
        )
        
        response = model.generate_content(question)
        reply = response.text
        
        await context.bot.send_message(chat_id=chat_id, text=reply)
        
    except Exception as e:
        logger.error(f"❌ خطا: {e}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت دکمه‌ها"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await query.edit_message_text("⛔ فقط صاحب ربات می‌تونه پاسخ بده.")
        return
    
    parts = data.split('_')
    action = parts[0]
    chat_id = int(parts[1])
    target_user_id = int(parts[2])
    
    if action == "answer":
        await query.edit_message_text(
            f"✅ پاسخ خودت رو به کاربر بفرست.\n"
            f"🆔 کاربر: `{target_user_id}`"
        )
        context.user_data['reply_to'] = target_user_id
        
        if target_user_id in pending_questions:
            del pending_questions[target_user_id]
        
    elif action == "robot":
        await query.edit_message_text("🤖 ربات در حال پاسخ‌دهی...")
        
        if target_user_id in pending_questions:
            data = pending_questions[target_user_id]
            question = data["question"]
            chat_id = data["chat_id"]
            
            del pending_questions[target_user_id]
            
            try:
                model = genai.GenerativeModel(
                    model_name=MODEL_NAME,
                    system_instruction=SYSTEM_PROMPT
                )
                
                response = model.generate_content(question)
                reply = response.text
                
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🤖 {reply}"
                )
                
            except Exception as e:
                await query.edit_message_text(f"❌ خطا: {e}")

async def reply_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پاسخ به کاربر از طرف شما"""
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        return
    
    reply_to = context.user_data.get('reply_to')
    
    if not reply_to:
        await update.message.reply_text("❌ ابتدا روی دکمه 'پاسخ خودم' کلیک کن.")
        return
    
    try:
        await context.bot.send_message(
            chat_id=reply_to,
            text=f"📩 {update.message.text}"
        )
        await update.message.reply_text("✅ پاسخ ارسال شد!")
        context.user_data['reply_to'] = None
        
    except Exception as e:
        await update.message.reply_text(f"❌ خطا: {e}")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.TEXT & filters.User(OWNER_ID), reply_to_user))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    logger.info("🚀 ربات روشن شد!")
    logger.info(f"👤 مالک: {OWNER_ID}")
    logger.info(f"🔧 مدل: {MODEL_NAME}")
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
