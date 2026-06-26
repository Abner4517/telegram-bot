
import os
import json
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler
import google.generativeai as genai

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
AUTHORIZED_USER_ID = int(os.environ.get("AUTHORIZED_USER_ID", "0"))

genai.configure(api_key=GEMINI_API_KEY)

chat_context = ""
export_path = "telegram_export.json"
if os.path.exists(export_path):
    with open(export_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    messages_list = []
    chats = data.get("chats", {}).get("list", [data]) if "chats" in data else [data]
    
    for chat in chats:
        for msg in chat.get("messages", []):
            if msg.get("type") == "message" and isinstance(msg.get("text"), str):
                sender = msg.get("from", "نامشخص")
                text = msg["text"].strip()
                if text:
                    messages_list.append(f"{sender}: {text}")
    
    recent = messages_list[-300:]
    chat_context = "\n".join(recent)
    logger.info(f"Loaded {len(recent)} messages from export.")
else:
    logger.warning("No telegram_export.json found. Running without chat history.")

SYSTEM_PROMPT = f"""تو یک دستیار هوشمند هستی که باید دقیقاً مثل صاحب این اکانت تلگرام جواب بدی.

برای این کار، تاریخچه‌ی چت‌های اخیر این شخص رو داری:

--- شروع تاریخچه چت ---
{chat_context if chat_context else "تاریخچه‌ای یافت نشد."}
--- پایان تاریخچه چت ---

بر اساس این چت‌ها:
- سبک نوشتاری، لحن، و شیوه پاسخ‌دهی این شخص رو یاد بگیر
- از همون کلمات، عبارات، و اختصارات که این شخص استفاده می‌کنه استفاده کن
- طول پیام‌ها رو مشابه حفظ کن
- اگه این شخص شوخ‌طبعه، شوخ باش. اگه رسمیه، رسمی باش.
- فقط به فارسی جواب بده مگه اینکه مکالمه به زبان دیگه‌ای باشه

مهم: تو داری به جای این شخص جواب می‌دی، نه به عنوان یه ربات."""

conversation_history = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if AUTHORIZED_USER_ID and user_id != AUTHORIZED_USER_ID:
        await update.message.reply_text("⛔ دسترسی مجاز نیست.")
        return
    await update.message.reply_text("✅ ربات آماده‌ست! پیام بفرست.")

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

    if len(conversation_history[chat_id]) > 40:
        conversation_history[chat_id] = conversation_history[chat_id][-40:]

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
        logger.error(f"Error: {e}")
        await update.message.reply_text("❌ خطایی رخ داد. لطفاً دوباره امتحان کن.")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if AUTHORIZED_USER_ID and user_id != AUTHORIZED_USER_ID:
        return
    chat_id = update.effective_chat.id
    conversation_history[chat_id] = []
    await update.message.reply_text("🔄 تاریخچه مکالمه پاک شد.")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot started...")
    app.run_polling()

if name == "main":
    main()
