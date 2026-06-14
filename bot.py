import os
import re
import json
import aiohttp
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

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

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


def get_sender_name(user):
    if user.id == ANYA_ID:
        return "Анюся"
    if user.id == KATYA_ID:
        return "Катерина"
    return user.first_name


def to_utc_naive(dt_moscow):
    return dt_moscow.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def clean_json(text: str):
    text = text.strip()
    text = re.sub(r"^```json", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"^```", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    return text


async def analyze_reminder_with_ai(user_text: str, sender: str):
    url = "https://api.aitunnel.ru/v1/chat/completions"

    now_moscow = datetime.now(MOSCOW_TZ)
    now_text = now_moscow.strftime("%Y-%m-%d %H:%M")

    headers = {
        "Authorization": f"Bearer {AITUNNEL_API_KEY}",
        "Content-Type": "application/json",
    }

    system_prompt = f"""
Ты парсер напоминаний для Telegram-бота.

Текущая дата и время по Москве: {now_text}.
Таймзона: Europe/Moscow.

Тебе нужно понять, является ли сообщение просьбой создать напоминание.

Верни СТРОГО JSON без markdown и без пояснений.

Формат ответа, если это напоминание:
{{
  "action": "create_reminder",
  "text": "что именно напомнить",
  "remind_at": "YYYY-MM-DD HH:MM",
  "human_time": "человеческое описание времени"
}}

Формат ответа, если это НЕ напоминание:
{{
  "action": "none"
}}

Правила:
- Понимай любые формулировки со словом "напомни", "напоминание", "поставь напоминание".
- Порядок слов может быть любым.
- Понимай такие варианты:
  "напомни через 5 минут позвонить клиенту"
  "через 5 минут напомни позвонить клиенту"
  "бот, напомни Кате позвонить мне через 1 минуту"
  "Кате напомни через час отправить договор"
  "напомни завтра в 10:00 проверить ипотеку"
  "завтра в 10 напомни проверить ипотеку"
  "напомни в понедельник в 12:00 проверить задачу"
  "напомни 25.06 в 15:00 отправить договор"
- Понимай: через 5 минут, через 2 часа, через день, через неделю, сегодня, завтра, послезавтра, дни недели, даты формата 25.06 и 25.06.2026.
- Если год не указан, используй ближайшую будущую дату.
- Если указано "Кате", "Катерине", "Анюсе", включи это в текст напоминания.
- Если время не указано вообще, верни action none.
- Если дата/время уже прошли, выбери ближайшую будущую дату.
- Не обещай ничего. Только JSON.

Отправитель сообщения: {sender}.
"""

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_text,
            },
        ],
        "temperature": 0,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload) as response:
            data = await response.json()
            raw = data["choices"][0]["message"]["content"]
            cleaned = clean_json(raw)

            try:
                return json.loads(cleaned)
            except Exception:
                return {"action": "none"}


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

Ты универсальный личный и командный ассистент Анюси и Катерины.

Ты можешь помогать с любыми бытовыми и рабочими задачами:
- недвижимость
- клиенты
- контент
- маркетинг
- тексты
- идеи
- планирование
- кино и книги
- здоровье и самочувствие
- обучение
- бытовые вопросы
- финансы на уровне общих объяснений
- путешествия
- технологии
- любые повседневные вопросы

Важные правила:
- Не ограничивайся недвижимостью.
- Если вопрос про здоровье, не ставь диагноз. Дай аккуратное объяснение, признаки риска и рекомендацию обратиться к врачу, если есть тревожные симптомы.
- Если вопрос требует актуальных данных, например погода, курс валют, новости, свежие цены, честно скажи, что у тебя в Telegram-боте нет прямого доступа к интернету, если такая интеграция еще не подключена.
- Не выдумывай факты.
- Если пользователь просит напомнить, не просто обещай. Напоминания создает технический модуль бота. Если модуль не сработал, попроси указать точное время.
- Отвечай понятно, живо и по делу.
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
        "Я универсальный ассистент: задачи, напоминания, тексты, идеи, быт, кино, здоровье, работа и не только.\n\n"
        "Напоминания можно писать обычным языком:\n"
        "• напомни через 15 минут позвонить клиенту\n"
        "• через 1 минуту напомни мне отправить договор\n"
        "• бот, напомни Кате через час отправить договор\n"
        "• напомни завтра в 10:00 проверить ипотеку\n\n"
        "Старый формат тоже работает:\n"
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

    add_reminder(
        chat_id=chat_id,
        text=f"{sender}: {text}",
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
    sender = get_sender_name(user)

    is_reply_to_bot = False

    if update.message.reply_to_message:
        if update.message.reply_to_message.from_user.id == context.bot.id:
            is_reply_to_bot = True

    has_reminder_word = (
        "напомни" in text_lower
        or "напоминание" in text_lower
    )

    trigger = (
        text_lower.startswith("бот")
        or text_lower.startswith("ассистент")
        or has_reminder_word
        or is_reply_to_bot
    )

    if not trigger:
        return

    if has_reminder_word:
        await update.message.chat.send_action("typing")

        reminder_result = await analyze_reminder_with_ai(
            user_text=user_text,
            sender=sender
        )

        if reminder_result.get("action") == "create_reminder":
            try:
                remind_at_moscow = datetime.strptime(
                    reminder_result["remind_at"],
                    "%Y-%m-%d %H:%M"
                ).replace(tzinfo=MOSCOW_TZ)

                remind_at_utc = to_utc_naive(remind_at_moscow)

                reminder_text = reminder_result["text"]
                human_time = reminder_result.get(
                    "human_time",
                    remind_at_moscow.strftime("%d.%m.%Y в %H:%M по МСК")
                )

                add_reminder(
                    chat_id=chat_id,
                    text=f"{sender}: {reminder_text}",
                    remind_at=remind_at_utc.isoformat()
                )

                await update.message.reply_text(
                    f"✅ Напоминание создано.\n\n"
                    f"{human_time}:\n"
                    f"{reminder_text}"
                )

                return

            except Exception as e:
                await update.message.reply_text(
                    f"Не смогла создать напоминание. Ошибка: {str(e)}"
                )
                return

        await update.message.reply_text(
            "Я поняла, что нужно напоминание, но не вижу точного времени.\n\n"
            "Напиши, например:\n"
            "напомни через 15 минут позвонить клиенту\n"
            "или\n"
            "напомни завтра в 10:00 проверить ипотеку"
        )
        return

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
