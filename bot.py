import os
import json
import logging
import asyncio
from datetime import datetime, timedelta
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

# ========== پرامپت ==========
SYSTEM_PROMPT = """تو یک دستیار هوشمند هستی که قراره به جای صاحبش صحبت کنی.

دستورالعمل‌ها:
۱. مثل یک انسان معمولی و خودمانی صحبت کن
۲. فقط به فارسی جواب بده
۳. از کلمات محاوره‌ای و صمیمی استفاده کن
۴. اگر چیزی نمی‌دونی، بگو "نمیدونم" یا "والا نمی‌دونم"
۵. هرگز نگو "من یک ربات هستم" یا "به عنوان هوش مصنوعی"
۶. پاسخ‌هات کوتاه و مختصر باشه (حداکثر ۲-۳ خط)
۷. با اعتماد به نفس و طبیعی صحبت کن

مهم: تو داری به جای یک شخص واقعی صحبت می‌کنی، پس کاملاً طبیعی و انسانی جواب بده."""

# ========== تاریخچه مکالمه ==========
conversation_history = {}
pending_questions = {}  # {user_id: {"question": text, "chat_id": id, "time": datetime}}

# کلمات کلیدی برای تشخیص سوالات سخت
HARD_QUESTIONS = [
    "حل کن", "راهنمایی کن", "نظریه", "برنامه", "کد", "پروژه",
    "تحلیل", "پژوهش", "مقاله", "ترجمه", "تخصصی", "پیشرفته",
    "الگوریتم", "ریاضی", "فیزیک", "شیمی", "برنامه‌نویسی"
]

def is_hard_question(text):
    """تشخیص سوال سخت یا تخصصی"""
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
        f"اگه ۵ دقیقه جواب ندم، خودم بهت پاسخ می‌دم."
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
        # ارسال پیام به شما
        try:
            forward_msg = (
                f"🔔 **سوال سخت از {user_name}**\n"
                f"👤 یوزرنیم: @{username}\n"
                f"🆔 آیدی: `{user_id}`\n\n"
                f"**سوال:**\n{user_text}\n\n"
                f"⏳ شما ۵ دقیقه وقت دارید تا پاسخ بدید.\n"
                f"اگه جواب ندی، ربات خودش پاسخ میده."
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
            
            # ذخیره سوال در صف
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
                f"⏱️ اگه ۵ دقیقه جواب ندم، خودم بهت پاسخ می‌دم.\n"
                f"اگه عجله داری، می‌تونی روی دکمه زیر کلیک کنی تا خودم جواب بدم. 👇"
            )
            
            # تنظیم تایمر ۵ دقیقه
            asyncio.create_task(auto_reply_after_timeout(user_id, context))
            return
            
        except Exception as e:
            logger.error(f"❌ خطا در ارسال به مالک: {e}")
            # اگه نتونست به شما پیام بده، خودش جواب بده
            pass

    # ========== پاسخ معمولی ==========
    # مدیریت تاریخچه
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
        
        # اگه ربات نتونست جواب بده، به شما اطلاع بده
        try:
            error_msg = (
                f"⚠️ **خطا در پاسخ به {user_name}**\n"
                f"👤 @{username}\n"
                f"🆔 `{user_id}`\n\n"
                f"**پیام:**\n{user_text}\n\n"
                f"**خطا:**\n{str(e)[:100]}"
            )
            await context.bot.send_message(chat_id=OWNER_ID, text=error_msg, parse_mode='Markdown')
        except:
            pass
        
        await update.message.reply_text(
            "❌ خطایی رخ داد! پیامت رو برای صاحبم فرستادم.\n"
            "به زودی پاسخ می‌دم. ⏳"
        )

async def auto_reply_after_timeout(user_id, context):
    """پاسخ خودکار بعد از ۵ دقیقه"""
    await asyncio.sleep(300)  # ۵ دقیقه
    
    # چک کن که هنوز سوال در صف هست
    if user_id not in pending_questions:
        return
    
    data = pending_questions[user_id]
    chat_id = data["chat_id"]
    question = data["question"]
    user_name = data["user_name"]
    
    # حذف از صف
    del pending_questions[user_id]
    
    try:
        # به کاربر اطلاع بده
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⏰ ۵ دقیقه گذشت و صاحبم جواب نداد.\n"
                 f"خودم به سوال شما پاسخ می‌دم. 🤖"
        )
        
        # پاسخ با ربات
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            system_instruction=SYSTEM_PROMPT
        )
        
        response = model.generate_content(question)
        reply = response.text
        
        # ذخیره در تاریخچه
        if chat_id not in conversation_history:
            conversation_history[chat_id] = []
        
        conversation_history[chat_id].append({
            "role": "user",
            "parts": [question]
        })
        conversation_history[chat_id].append({
            "role": "model",
            "parts": [reply]
        })
        
        await context.bot.send_message(chat_id=chat_id, text=reply)
        
        # به مالک اطلاع بده که ربات پاسخ داد
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=f"🤖 ربات به {user_name} پاسخ داد (وقت شما تموم شد)."
        )
        
    except Exception as e:
        logger.error(f"❌ خطا در پاسخ خودکار: {e}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت دکمه‌ها"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = update.effective_user.id
    
    # فقط مالک می‌تونه پاسخ بده
    if user_id != OWNER_ID:
        await query.edit_message_text("⛔ فقط صاحب ربات می‌تونه پاسخ بده.")
        return
    
    parts = data.split('_')
    action = parts[0]
    chat_id = int(parts[1])
    target_user_id = int(parts[2])
    
    if action == "answer":
        # کاربر می‌خواد خودش پاسخ بده
        await query.edit_message_text(
            f"✅ پاسخ خودت رو به کاربر بفرست.\n"
            f"🆔 کاربر: `{target_user_id}`\n\n"
            f"💡 فقط کافی پیامت رو به ربات بفرستی تا به کاربر برسه."
        )
        # ذخیره در context برای پاسخ بعدی
        context.user_data['reply_to'] = target_user_id
        context.user_data['reply_chat'] = chat_id
        
        # حذف از صف تا ربات پاسخ نده
        if target_user_id in pending_questions:
            del pending_questions[target_user_id]
        
    elif action == "robot":
        # بذار ربات جواب بده
        await query.edit_message_text("🤖 ربات در حال پاسخ‌دهی به کاربر...")
        
        # حذف از صف
        if target_user_id in pending_questions:
            data = pending_questions[target_user_id]
            question = data["question"]
            user_name = data["user_name"]
            chat_id = data["chat_id"]
            
            del pending_questions[target_user_id]
            
            try:
                model = genai.GenerativeModel(
                    model_name="gemini-1.5-flash",
                    system_instruction=SYSTEM_PROMPT
                )
                
                response = model.generate_content(question)
                reply = response.text
                
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🤖 **پاسخ ربات:**\n\n{reply}"
                )
                
                await query.edit_message_text(
                    f"✅ ربات به {user_name} پاسخ داد."
                )
                
            except Exception as e:
                await query.edit_message_text(f"❌ خطا: {e}")

async def reply_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پاسخ به کاربر از طرف شما"""
    user_id = update.effective_user.id
    
    # فقط مالک
    if user_id != OWNER_ID:
        return
    
    reply_to = context.user_data.get('reply_to')
    reply_chat = context.user_data.get('reply_chat')
    
    if not reply_to:
        await update.message.reply_text(
            "❌ ابتدا روی دکمه 'پاسخ خودم' کلیک کن.\n"
            "یا از دستور /reply <آیدی> <پیام> استفاده کن."
        )
        return
    
    # ارسال پاسخ به کاربر
    try:
        await context.bot.send_message(
            chat_id=reply_to,
            text=f"📩 **پاسخ صاحب ربات:**\n\n{update.message.text}"
        )
        
        await update.message.reply_text("✅ پاسخ ارسال شد!")
        
        # پاک کردن context
        context.user_data['reply_to'] = None
        context.user_data['reply_chat'] = None
        
    except Exception as e:
        await update.message.reply_text(f"❌ خطا: {e}")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /broadcast - ارسال پیام به همه کاربران (فقط مالک)"""
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("⛔ فقط صاحب ربات می‌تونه این کار رو بکنه.")
        return
    
    msg = " ".join(context.args)
    if not msg:
        await update.message.reply_text("❌ پیام رو وارد کن: /broadcast سلام")
        return
    
    await update.message.reply_text("✅ پیام به همه کاربران ارسال شد!")

async def reply_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /reply <user_id> <message>"""
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("⛔ فقط مالک.")
        return
    
    try:
        target_id = int(context.args[0])
        msg = " ".join(context.args[1:])
        
        if not msg:
            await update.message.reply_text("❌ پیام رو وارد کن: /reply 123456 سلام")
            return
        
        await context.bot.send_message(
            chat_id=target_id,
            text=f"📩 **پاسخ صاحب ربات:**\n\n{msg}"
        )
        await update.message.reply_text("✅ پاسخ ارسال شد!")
        
    except Exception as e:
        await update.message.reply_text(f"❌ خطا: {e}")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # هندلرها
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("reply", reply_command))
    
    # هندلر پیام‌ها
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # هندلر برای پاسخ شما به کاربر
    app.add_handler(MessageHandler(filters.TEXT & filters.User(OWNER_ID), reply_to_user))
    
    # هندلر دکمه‌ها
    app.add_handler(CallbackQueryHandler(button_callback))
    
    logger.info("🚀 ربات هوشمند روشن شد!")
    logger.info(f"👤 مالک: {OWNER_ID}")
    logger.info("⏳ تایمر ۵ دقیقه برای پاسخ فعال است!")
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
