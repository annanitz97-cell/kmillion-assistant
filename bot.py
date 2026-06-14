import os
import re
import aiohttp
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from memory import save_message, get_last_messages
from reminders import add_reminder, get_due_reminders, mark_sent


BOT_TOKEN = os.getenv("BOT_TOKEN")
AITUNNEL_API_KEY = os.getenv("AITUNNEL_API_KEY")
MODEL = os.getenv("MODEL", "gpt-4.1-mini")

ANYA_ID = 274320100
KATYA_ID = 135392354


def get_sender_name(user):
    if user.id == ANYA_ID:
        return "Анюся"
    if user.id == KATYA_ID:
        return "Катерина"
    return user.first_name


def parse_natural_reminder(text: str):
    text = text.strip()

    # Убираем обращение к боту, если оно есть
    text = re.sub(r"^(бот|ассистент)[,\s]+", "", text, flags=re.IGNORECASE)

    pattern = r"^напомни\s+через\s+(\d+)\s*(мин|минут|минуту|минуты|час|часа|часов)\s+(.+)$"

    match = re.match(pattern, text, flags=re.IGNORECASE)

    if not match:
        return None

    amount = int(match.group(1))
    unit = match.group(2).lower()
    reminder_text = match.group(3).strip()

    if unit.startswith("мин"):
        remind_at = datetime.utcnow() + timedelta(minutes=amount)
        human_time = f"через {amount} мин."

    elif unit.startswith("час"):
        remind_at = datetime.utcnow() + timedelta(hours=amount)
        human_time = f"через {amount} ч."

    else:
        return None

    return reminder_text, remind_at, human_time


async def ask_ai(message: str):
    url = "https://api.aitunnel.ru/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {AITUNNEL_API_KEY}",
        "Content-Type": "application/json",
    }

    messages = [
        {
            "role": "system",
            "content": """
Ты KMillion Assistant.

Ты ассистент агентства недвижимости.

В команде два партнера:
- Анюся
- Катерина

Важно:
Если пользователь просит напомнить, но пишет это обычным языком,
бот сам создает напоминание, если фраза в формате:
"напомни через 15 мин позвонить клиенту"
или
"напомни через 2 часа отправить договор".

Отвечай кратко, понятно и по делу.
"""
        }
    ]

    messages.extend(get_last_messages(100))

    messages.append({
        "role": "user",
        "content": message
    })

    payload = {
        "model": MODEL,
        "messages": messages
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as response:
            data = await response.json()

            answer = data["choices"][0]["message"]["content"]

            save_message("team", "user", message)
            save_message("team", "assistant", answer)

            return answer


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я KMillion Assistant 🚀\n\n"
        "Теперь можно писать так:\n"
        "напомни через 15 мин позвонить Кате\n\n"
        "Или старым способом:\n"
        "/remind 10 позвонить клиенту"
    )


async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    await update.message.reply_text(
        f"👤 Имя: {user.first_name}\n"
        f"🆔 ID: {user.id}\n"
        f"📎 Username: @{user.username if user.username else 'нет'}"
    )


async def remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user

    if len(context.args) < 2:
        await update.message.reply_text(
            "Формат такой:\n"
            "/remind 10 позвонить клиенту\n\n"
            "10 — количество минут."
        )
        return

    try:
        minutes = int(context.args[0])
    except ValueError:
        await update.message.reply_text(
            "Первым числом укажи количество минут.\n\n"
            "Пример:\n"
            "/remind 5 проверить ипотеку"
        )
        return

    text = " ".join(context.args[1:])
    remind_at = datetime.utcnow() + timedelta(minutes=minutes)

    sender = get_sender_name(user)
    reminder_text = f"{sender}: {text}"

    add_reminder(
        chat_id=chat_id,
        text=reminder_text,
        remind_at=remind_at.isoformat()
    )

    await update.message.reply_text(
        f"✅ Напоминание создано.\n\n"
        f"Через {minutes} мин:\n"
        f"{text}"
    )


async def check_reminders(application: Application):
    due_reminders = get_due_reminders()

    for reminder_id, chat_id, text in due_reminders:
        try:
            await application.bot.send_message(
                chat_id=chat_id,
                text=f"🔔 Напоминание\n\n{text}"
            )

            mark_sent(reminder_id)

        except Exception as e:
            print(f"Ошибка отправки напоминания: {e}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_text = update.message.text
    chat_id = update.effective_chat.id

    text_lower = user_text.lower().strip()

    # 1. Сначала проверяем естественные напоминания
    reminder = parse_natural_reminder(user_text)

    if reminder:
        reminder_text, remind_at, human_time = reminder

        sender = get_sender_name(user)

        add_reminder(
            chat_id=chat_id,
            text=f"{sender}: {reminder_text}",
            remind_at=remind_at.isoformat()
        )

        await update.message.reply_text(
            f"✅ Напоминание создано.\n\n"
            f"{human_time}:\n"
            f"{reminder_text}"
        )

        return

    # 2. Потом обычный фильтр обращения к боту
    trigger = (
        text_lower.startswith("бот")
        or text_lower.startswith("ассистент")
    )

    if update.message.reply_to_message:
        if update.message.reply_to_message.from_user.id == context.bot.id:
            trigger = True

    if not trigger:
        return

    sender = get_sender_name(user)

    full_prompt = f"""
Сообщение от: {sender}

Текст сообщения:
{user_text}
"""

    await update.message.chat.send_action("typing")

    try:
        answer = await ask_ai(full_prompt)
        await update.message.reply_text(answer)

    except Exception as e:
        await update.message.reply_text(
            f"Ошибка: {str(e)}"
        )


app = Application.builder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("id", my_id))
app.add_handler(CommandHandler("remind", remind))

app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    )
)

scheduler = AsyncIOScheduler()
scheduler.add_job(
    check_reminders,
    "interval",
    seconds=30,
    args=[app]
)
scheduler.start()

print("KMillion Assistant запущен")

app.run_polling()
