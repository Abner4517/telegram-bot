import os
import json
import logging
import re
from datetime import datetime
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
import google.generativeai as genai

# ========== تنظیمات اولیه ==========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# متغیرهای محیطی
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
AUTHORIZED_USER_ID = int(os.environ.get("AUTHORIZED_USER_ID", "0"))

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    logger.error("❌ متغیرهای محیطی تنظیم نشده!")
    exit(1)

genai.configure(api_key=GEMINI_API_KEY)

# ========== آنالیز و بارگذاری هوشمند تاریخچه ==========
class ChatAnalyzer:
    """آنالیزگر چت‌ها برای استخراج ویژگی‌های شخصیتی"""
    
    def __init__(self):
        self.messages = []
        self.personality_traits = {
            "tone": "محاوره‌ای",  # رسمی / محاوره‌ای / شوخ
            "emoji_usage": "متوسط",
            "response_length": "متوسط",
            "topics": [],
            "common_phrases": [],
            "writing_style": ""
        }
    
    def load_from_json(self, file_path):
        """بارگذاری و آنالیز فایل JSON"""
        if not os.path.exists(file_path):
            logger.warning(f"⚠️ فایل {file_path} پیدا نشد")
            return False
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # استخراج پیام‌ها
            messages = []
            
            if "chats" in data:
                for chat in data["chats"].get("list", []):
                    for msg in chat.get("messages", []):
                        text = self._extract_text(msg)
                        if text and len(text) > 3:
                            sender = msg.get("from", "")
                            date = msg.get("date", "")
                            messages.append({
                                "sender": sender,
                                "text": text,
                                "date": date
                            })
            elif "messages" in data:
                for msg in data.get("messages", []):
                    text = self._extract_text(msg)
                    if text and len(text) > 3:
                        sender = msg.get("from", "")
                        date = msg.get("date", "")
                        messages.append({
                            "sender": sender,
                            "text": text,
                            "date": date
                        })
            
            if messages:
                self.messages = messages
                self._analyze_personality()
                logger.info(f"✅ {len(messages)} پیام بارگذاری شد")
                return True
            else:
                logger.warning("⚠️ پیامی یافت نشد")
                return False
                
        except Exception as e:
            logger.error(f"❌ خطا در بارگذاری: {e}")
            return False
    
    def _extract_text(self, msg):
        """استخراج متن از پیام"""
        if not msg:
            return None
        
        text = msg.get("text")
        if isinstance(text, str):
            return text.strip()
        elif isinstance(text, list):
            parts = []
            for part in text:
                if isinstance(part, dict) and "text" in part:
                    parts.append(part["text"])
                elif isinstance(part, str):
                    parts.append(part)
            return " ".join(parts).strip()
        return None
    
    def _analyze_personality(self):
        """آنالیز شخصیت از روی پیام‌ها"""
        if not self.messages:
            return
        
        # فقط پیام‌های خود شخص (با فرض اینکه نامش در export مشخصه)
        # اگه نام مشخص نیست، از همه پیام‌ها استفاده می‌کنیم
        user_messages = [m["text"] for m in self.messages if m["sender"] != ""]
        
        if not user_messages:
            user_messages = [m["text"] for m in self.messages]
        
        # تحلیل طول پیام‌ها
        avg_length = sum(len(msg) for msg in user_messages) / len(user_messages) if user_messages else 0
        if avg_length < 50:
            self.personality_traits["response_length"] = "کوتاه و مختصر"
        elif avg_length < 200:
            self.personality_traits["response_length"] = "متوسط"
        else:
            self.personality_traits["response_length"] = "طولانی و مفصل"
        
        # تحلیل ایموجی‌ها
        emoji_pattern = re.compile("["
            u"\U0001F600-\U0001F64F"  # ایموجی‌های احساسی
            u"\U0001F300-\U0001F5FF"  # نمادها و پرچم‌ها
            u"\U0001F680-\U0001F6FF"  # حمل و نقل و نقشه
            u"\U0001F700-\U0001F77F"  # آیکون‌های مختلف
            u"\U0001F780-\U0001F7FF"  # اشکال هندسی
            u"\U0001F800-\U0001F8FF"  # فلش‌ها
            u"\U0001F900-\U0001F9FF"  # مکمل‌های ایموجی
            u"\U0001FA00-\U0001FA6F"  # مکمل‌های بیشتر
            u"\U0001FA70-\U0001FAFF"  # مکمل‌های بیشتر
            u"\U00002702-\U000027B0"  # نمادهای مختلف
            u"\U000024C2-\U0001F251" 
            "]+", flags=re.UNICODE)
        
        emoji_count = sum(1 for msg in user_messages if emoji_pattern.search(msg))
        emoji_ratio = emoji_count / len(user_messages) if user_messages else 0
        
        if emoji_ratio > 0.5:
            self.personality_traits["emoji_usage"] = "زیاد (عاشق ایموجیه!)"
        elif emoji_ratio > 0.2:
            self.personality_traits["emoji_usage"] = "متوسط"
        else:
            self.personality_traits["emoji_usage"] = "کم (مختصر و مفید)"
        
        # پیدا کردن کلمات پرتکرار (برای تشخیص لحن)
        all_text = " ".join(user_messages)
        words = re.findall(r'\w+', all_text)
        
        # کلمات خاص فارسی
        informal_words = ["آره", "نه", "اوکی", "خب", "باشه", "مرسی", "داداش", "دختر", "عمو", "خواهر"]
        formal_words = ["بله", "خیر", "متشکرم", "خواهش می‌کنم", "جناب", "سرکار"]
        
        informal_count = sum(1 for w in words if w in informal_words)
        formal_count = sum(1 for w in words if w in formal_words)
        
        if informal_count > formal_count:
            self.personality_traits["tone"] = "خودمانی و صمیمی"
        elif formal_count > informal_count:
            self.personality_traits["tone"] = "رسمی و مودب"
        else:
            self.personality_traits["tone"] = "متوسط (هم رسمی هم خودمانی)"
        
        # پیدا کردن عبارت‌های تکراری
        phrases = []
        for i in range(len(user_messages) - 1):
            if len(user_messages[i]) < 100:
                phrases.append(user_messages[i][:30])
        
        from collections import Counter
        common_phrases = Counter(phrases).most_common(5)
        self.personality_traits["common_phrases"] = [p[0] for p in common_phrases if p[1] > 1]
        
        # سبک نوشتاری
        if "؟" in all_text and "!" in all_text:
            self.personality_traits["writing_style"] = "پراحساس و پرسشگر"
        elif "؟" in all_text:
            self.personality_traits["writing_style"] = "کنجکاو و پرسشگر"
        elif "!" in all_text:
            self.personality_traits["writing_style"] = "پرانرژی و هیجانی"
        else:
            self.personality_traits["writing_style"] = "متعادل و آرام"
        
        logger.info(f"📊 شخصیت شناسایی شد: {self.personality_traits}")

# ========== بارگذاری و آنالیز ==========
analyzer = ChatAnalyzer()
history_loaded = analyzer.load_from_json("telegram_export.json")

# گرفتن نمونه‌هایی از پیام‌های خود شخص برای پرامپت
sample_messages = []
if history_loaded and analyzer.messages:
    # گرفتن ۲۰ پیام آخر خود شخص
    user_msgs = [m for m in analyzer.messages if m["sender"] != ""]
    if not user_msgs:
        user_msgs = analyzer.messages
    sample_messages = [m["text"] for m in user_msgs[-20:]]

# ========== ساخت پرامپت هوشمند ==========
def build_smart_prompt():
    """ساخت پرامپت بر اساس آنالیز شخصیت"""
    
    traits = analyzer.personality_traits
    
    prompt = f"""تو یک دستیار هوشمند هستی که باید دقیقاً مثل صاحب این اکانت تلگرام جواب بدی.

**ویژگی‌های شناسایی شده از شخصیت:**
- لحن: {traits['tone']}
- طول پاسخ‌ها: {traits['response_length']}
- استفاده از ایموجی: {traits['emoji_usage']}
- سبک نوشتاری: {traits['writing_style']}

**نمونه‌هایی از پاسخ‌های واقعی این شخص:**
"""
    
    # اضافه کردن نمونه پیام‌ها
    for i, msg in enumerate(sample_messages[:10], 1):
        prompt += f"{i}. {msg}\n"
    
    prompt += f"""
**دستورالعمل‌ها:**
۱. دقیقاً با همان لحن و سبک نمونه‌ها پاسخ بده
۲. طول پاسخ‌ها رو مثل نمونه‌ها حفظ کن (حدوداً {traits['response_length']})
۳. {traits['emoji_usage']} از ایموجی استفاده کن
۴. از کلمات و عبارات تکراری این شخص استفاده کن
۵. کاملاً طبیعی و انسانی صحبت کن، نه مثل یک ربات
۶. اگر سوالی پرسیده شد که پاسخش رو نمی‌دونی، بگو "نمیدونم" یا "والا نمی‌دونم" به سبک خودش
۷. به فارسی پاسخ بده مگر اینکه سوال به زبان دیگه‌ای باشه

مهم: تو داری به جای این شخص صحبت می‌کنی. هویت خودت رو به عنوان یک شخص حفظ کن و هیچ‌وقت نگو "من یک ربات هستم" یا "به عنوان هوش مصنوعی".
"""
    
    return prompt

# ساخت پرامپت نهایی
SYSTEM_PROMPT = build_smart_prompt()
logger.info("✅ پرامپت هوشمند ساخته شد")

# ========== مدیریت ربات ==========
conversation_history = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /start"""
    user_id = update.effective_user.id
    if AUTHORIZED_USER_ID and user_id != AUTHORIZED_USER_ID:
        await update.message.reply_text("⛔ دسترسی مجاز نیست.")
        return
    
    status = "✅ بارگذاری شده" if history_loaded else "❌ بارگذاری نشده"
    msg_count = len(analyzer.messages) if history_loaded else 0
    
    await update.message.reply_text(
        f"👋 سلام! من با شخصیت تو صحبت می‌کنم.\n\n"
        f"📊 وضعیت: {status}\n"
        f"💬 تعداد پیام‌های آنالیز شده: {msg_count}\n"
        f"🎭 سبک شناسایی شده: {analyzer.personality_traits['tone']}\n\n"
        f"هر چی بپرسی، دقیقاً مثل خودت جواب می‌دم! 🎯\n"
        f"برای دیدن آمار: /stats\n"
        f"برای پاک کردن تاریخچه: /reset"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت پیام‌ها"""
    user_id = update.effective_user.id
    
    if AUTHORIZED_USER_ID and user_id != AUTHORIZED_USER_ID:
        await update.message.reply_text("⛔ دسترسی مجاز نیست.")
        return

    user_text = update.message.text
    chat_id = update.effective_chat.id

    # مدیریت تاریخچه مکالمه
    if chat_id not in conversation_history:
        conversation_history[chat_id] = []
    
    conversation_history[chat_id].append({
        "role": "user",
        "parts": [user_text]
    })

    if len(conversation_history[chat_id]) > 50:
        conversation_history[chat_id] = conversation_history[chat_id][-50:]

    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        
        # استفاده از پرامپت پویا
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
        
        # ارسال پاسخ
        if len(reply) > 4000:
            for i in range(0, len(reply), 4000):
                await update.message.reply_text(reply[i:i+4000])
        else:
            await update.message.reply_text(reply)
        
        logger.info(f"✅ پاسخ ارسال شد به {chat_id}")
        
    except Exception as e:
        logger.error(f"❌ خطا: {e}")
        await update.message.reply_text(
            f"❌ یه مشکلی پیش اومد! 😅\n"
            f"دوباره امتحان کن یا /reset بزن."
        )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /stats - نمایش آمار کامل"""
    user_id = update.effective_user.id
    if AUTHORIZED_USER_ID and user_id != AUTHORIZED_USER_ID:
        return
    
    traits = analyzer.personality_traits
    
    stats_text = f"""📊 **آمار ربات شخصیت‌ساز**

**وضعیت تاریخچه:**
• تعداد پیام‌های آنالیز شده: {len(analyzer.messages)}
• تاریخچه بارگذاری: {'✅ بله' if history_loaded else '❌ خیر'}

**شخصیت شناسایی شده:**
• لحن: {traits['tone']}
• طول پاسخ: {traits['response_length']}
• ایموجی: {traits['emoji_usage']}
• سبک نوشتاری: {traits['writing_style']}

**تاریخچه مکالمه فعلی:**
• تعداد پیام‌ها: {len(conversation_history.get(update.effective_chat.id, []))}

**عبارات تکراری:**
"""
    
    for phrase in traits.get('common_phrases', [])[:3]:
        stats_text += f"• \"{phrase}\"\n"
    
    await update.message.reply_text(stats_text)

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /reset"""
    user_id = update.effective_user.id
    if AUTHORIZED_USER_ID and user_id != AUTHORIZED_USER_ID:
        return
    
    chat_id = update.effective_chat.id
    conversation_history[chat_id] = []
    await update.message.reply_text("🔄 تاریخچه پاک شد. از اول شروع کنیم! 😊")

async def reload_personality(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /reload - بارگذاری مجدد و آنالیز دوباره"""
    user_id = update.effective_user.id
    if AUTHORIZED_USER_ID and user_id != AUTHORIZED_USER_ID:
        return
    
    await update.message.reply_text("🔄 در حال آنالیز مجدد شخصیت...")
    
    global history_loaded, SYSTEM_PROMPT, analyzer
    analyzer = ChatAnalyzer()
    history_loaded = analyzer.load_from_json("telegram_export.json")
    SYSTEM_PROMPT = build_smart_prompt()
    
    await update.message.reply_text(
        f"✅ شخصیت دوباره آنالیز شد!\n"
        f"🎭 لحن: {analyzer.personality_traits['tone']}\n"
        f"📝 {len(analyzer.messages)} پیام جدید بارگذاری شد."
    )

# ========== اجرا ==========
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # اضافه کردن هندلرها
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("reload", reload_personality))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    logger.info("🚀 ربات شخصیت‌ساز روشن شد!")
    logger.info(f"👤 کاربر مجاز: {AUTHORIZED_USER_ID}")
    logger.info(f"📊 وضعیت تاریخچه: {'✅' if history_loaded else '❌'}")
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
