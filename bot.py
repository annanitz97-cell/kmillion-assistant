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
from knowledge import remember, get_knowledge, forget_item
from tasks import add_task, get_open_tasks, close_task


BOT_TOKEN = os.getenv("BOT_TOKEN")
AITUNNEL_API_KEY = os.getenv("AITUNNEL_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
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


async def tavily_search(query: str):
    url = "https://api.tavily.com/search"

    payload = {
        "api_key": TAVILY_API_KEY,
        "query": query,
        "search_depth": "basic",
        "max_results": 5,
        "include_answer": True,
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as response:
            return await response.json()


async def should_use_web(user_text: str):
    text = user_text.lower()

    keywords = [
        "погода", "сейчас", "сегодня", "новости", "курс", "доллар", "евро",
        "ставка", "цб", "ключевая", "кто выиграл", "результат", "матч",
        "свежие", "новые", "новинка", "вышли", "2026", "2027",
        "цена", "стоимость", "актуально", "последние", "последний",
        "найди", "поищи", "проверь"
    ]

    return any(word in text for word in keywords)


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

Верни СТРОГО JSON без markdown и пояснений.

Если это напоминание:
{{
  "action": "create_reminder",
  "text": "что именно напомнить",
  "remind_at": "YYYY-MM-DD HH:MM",
  "human_time": "человеческое описание времени"
}}

Если это НЕ напоминание:
{{
  "action": "none"
}}

Правила:
- Понимай любые формулировки со словом "напомни", "напоминание", "поставь напоминание".
- Порядок слов может быть любым.
- Понимай: через 5 минут, через 2 часа, через день, через неделю, сегодня, завтра, послезавтра, дни недели, 25.06, 25.06.2026.
- Если год не указан, используй ближайшую будущую дату.
- Если указано "Кате", "Катерине", "Анюсе", включи это в текст напоминания.
- Если время не указано вообще, верни action none.
- Если дата/время уже прошли, выбери ближайшую будущую дату.

Отправитель: {sender}.
"""

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
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


async def analyze_task_with_ai(user_text: str, sender: str):
    url = "https://api.aitunnel.ru/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {AITUNNEL_API_KEY}",
        "Content-Type": "application/json",
    }

    system_prompt = f"""
Ты парсер задач для Telegram-бота.

Верни СТРОГО JSON без markdown и пояснений.

Если пользователь хочет создать задачу:
{{
  "action": "create_task",
  "person": "Анюся или Катерина или Команда",
  "task": "текст задачи"
}}

Если это не создание задачи:
{{
  "action": "none"
}}

Правила:
- Понимай формулировки: "задача Катерине", "поставь задачу Анюсе", "надо сделать", "Катерине: проверить договор".
- Если исполнитель не указан, ставь "Команда".
- Отправитель: {sender}.
"""

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
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

    knowledge_items = get_knowledge()
    knowledge_text = "\n".join([f"{item_id}. {text}" for item_id, text in knowledge_items])

    messages = [
        {
            "role": "system",
            "content": f"""
Ты KMillion Assistant.

Ты универсальный личный и командный ассистент Анюси и Катерины.

Ты помогаешь с любыми бытовыми и рабочими задачами:
недвижимость, клиенты, контент, маркетинг, тексты, идеи, планирование, кино, книги,
здоровье, обучение, бытовые вопросы, финансы, путешествия, технологии.

Долговременная память команды:
{knowledge_text if knowledge_text else "Пока пусто."}

Правила:
- Не ограничивайся недвижимостью.
- Если в сообщении есть свежие данные из интернета, используй их.
- Если вопрос про здоровье, не ставь диагноз.
- Не выдумывай факты.
- Отвечай понятно, живо и по делу.
"""
        }
    ]

    messages.extend(get_last_messages(100))
    messages.append({"role": "user", "content": message})

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
        "Умею: интернет-поиск, напоминания, память, задачи, тексты, идеи, быт, кино, здоровье и работу.\n\n"
        "Примеры:\n"
        "бот, запомни: Катерина отвечает за ипотеку\n"
        "бот, что ты помнишь?\n"
        "бот, задача Катерине: проверить ДДУ\n"
        "бот, покажи задачи\n"
        "бот, закрой задачу 3\n"
        "напомни завтра в 10:00 позвонить клиенту"
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
        await update.message.reply_text("Формат: /remind 10 позвонить клиенту")
        return

    try:
        minutes = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Первым числом укажи количество минут.")
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
        f"✅ Напоминание создано.\n\nЧерез {minutes} мин:\n{text}"
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


def format_tasks(tasks):
    if not tasks:
        return "Открытых задач пока нет."

    text = "📌 Открытые задачи:\n\n"

    for task_id, person, task in tasks:
        text += f"{task_id}. {person}: {task}\n"

    return text


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

    has_reminder_word = "напомни" in text_lower or "напоминание" in text_lower

    trigger = (
        text_lower.startswith("бот")
        or text_lower.startswith("ассистент")
        or has_reminder_word
        or is_reply_to_bot
    )

    if not trigger:
        return

    clean_text = re.sub(r"^(бот|ассистент)[,\s]+", "", user_text, flags=re.IGNORECASE).strip()
    clean_lower = clean_text.lower()

    # ДОЛГОВРЕМЕННАЯ ПАМЯТЬ
    if clean_lower.startswith("запомни"):
        memory_text = re.sub(r"^запомни[:\s]*", "", clean_text, flags=re.IGNORECASE).strip()

        if not memory_text:
            await update.message.reply_text("Что именно запомнить?")
            return

        remember(memory_text)
        await update.message.reply_text(f"✅ Запомнила:\n{memory_text}")
        return

    if "что ты помнишь" in clean_lower or "покажи память" in clean_lower:
        items = get_knowledge()

        if not items:
            await update.message.reply_text("Память пока пустая.")
            return

        text = "🧠 Я помню:\n\n"
        for item_id, item_text in items:
            text += f"{item_id}. {item_text}\n"

        await update.message.reply_text(text)
        return

    if clean_lower.startswith("забудь"):
        match = re.search(r"\d+", clean_lower)

        if not match:
            await update.message.reply_text("Напиши номер, который нужно забыть. Например: бот, забудь 3")
            return

        forget_item(int(match.group()))
        await update.message.reply_text(f"✅ Удалила из памяти пункт {match.group()}")
        return

    # ЗАДАЧИ
    if "покажи задачи" in clean_lower or "задачи команды" in clean_lower:
        await update.message.reply_text(format_tasks(get_open_tasks()))
        return

    if clean_lower.startswith("закрой задачу"):
        match = re.search(r"\d+", clean_lower)

        if not match:
            await update.message.reply_text("Укажи номер задачи. Например: бот, закрой задачу 3")
            return

        close_task(int(match.group()))
        await update.message.reply_text(f"✅ Задача {match.group()} закрыта")
        return

    if "задача" in clean_lower or "поставь задачу" in clean_lower:
        task_result = await analyze_task_with_ai(clean_text, sender)

        if task_result.get("action") == "create_task":
            person = task_result.get("person", "Команда")
            task = task_result.get("task", "").strip()

            if not task:
                await update.message.reply_text("Я поняла, что это задача, но не вижу текст задачи.")
                return

            add_task(person, task)
            await update.message.reply_text(
                f"✅ Задача создана.\n\nИсполнитель: {person}\nЗадача: {task}"
            )
            return

    # НАПОМИНАНИЯ
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
                    f"✅ Напоминание создано.\n\n{human_time}:\n{reminder_text}"
                )
                return

            except Exception as e:
                await update.message.reply_text(f"Не смогла создать напоминание. Ошибка: {str(e)}")
                return

        await update.message.reply_text(
            "Я поняла, что нужно напоминание, но не вижу точного времени.\n\n"
            "Например: напомни завтра в 10:00 позвонить клиенту"
        )
        return

    # ОБЫЧНЫЙ ЧАТ + ИНТЕРНЕТ
    await update.message.chat.send_action("typing")

    try:
        if await should_use_web(user_text):
            search_data = await tavily_search(user_text)

            web_context = ""

            if search_data.get("answer"):
                web_context += f"\nКраткий ответ Tavily:\n{search_data.get('answer')}\n"

            for item in search_data.get("results", [])[:5]:
                web_context += f"""
Источник: {item.get('title', '')}
URL: {item.get('url', '')}
Фрагмент: {item.get('content', '')}
"""

            full_prompt = f"""
Сообщение от: {sender}

Пользователь спросил:
{user_text}

Свежие данные из интернета:
{web_context}

Ответь на русском языке.
Если источники противоречат друг другу, скажи об этом.
"""

        else:
            full_prompt = f"""
Сообщение от: {sender}

Текст сообщения:
{user_text}
"""

        answer = await ask_ai(full_prompt)
        await update.message.reply_text(answer)

    except Exception as e:
        await update.message.reply_text(f"Ошибка: {str(e)}")


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
