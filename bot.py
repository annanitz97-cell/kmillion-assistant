import os
import re
import json
import aiohttp
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from memory import save_message, get_last_messages
from reminders import add_reminder, get_due_reminders, mark_sent
from knowledge import remember, get_knowledge, forget_item
from tasks import add_task, get_open_tasks, close_task
from calendar_events import (
    add_event,
    get_events_for_day,
    get_events_for_next_days,
    delete_event,
)


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


def main_menu():
    keyboard = [
        [
            InlineKeyboardButton("📌 Задачи", callback_data="tasks"),
            InlineKeyboardButton("👥 Клиенты", callback_data="clients"),
        ],
        [
            InlineKeyboardButton("📅 Календарь", callback_data="calendar"),
            InlineKeyboardButton("🔔 Напоминания", callback_data="reminders"),
        ],
        [
            InlineKeyboardButton("🧠 Память", callback_data="memory"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def calendar_menu():
    keyboard = [
        [
            InlineKeyboardButton("Сегодня", callback_data="calendar_today"),
            InlineKeyboardButton("Завтра", callback_data="calendar_tomorrow"),
        ],
        [
            InlineKeyboardButton("Неделя", callback_data="calendar_week"),
            InlineKeyboardButton("➕ Как добавить", callback_data="calendar_add_help"),
        ],
        [
            InlineKeyboardButton("⬅️ Назад", callback_data="main_menu"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def format_events(events):
    if not events:
        return "📅 В расписании пока пусто."

    text = "📅 Расписание:\n\n"
    for event_id, title, event_at, created_by in events:
        text += f"{event_id}. {event_at} — {title}\nСоздала: {created_by}\n\n"
    return text.strip()


def format_tasks(tasks):
    if not tasks:
        return "📌 Открытых задач пока нет."

    text = "📌 Открытые задачи:\n\n"
    for task_id, person, task in tasks:
        text += f"{task_id}. {person}: {task}\n"
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
            try:
                return json.loads(clean_json(raw))
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
            try:
                return json.loads(clean_json(raw))
            except Exception:
                return {"action": "none"}


async def analyze_event_with_ai(user_text: str, sender: str):
    url = "https://api.aitunnel.ru/v1/chat/completions"
    now_moscow = datetime.now(MOSCOW_TZ)
    now_text = now_moscow.strftime("%Y-%m-%d %H:%M")

    headers = {
        "Authorization": f"Bearer {AITUNNEL_API_KEY}",
        "Content-Type": "application/json",
    }

    system_prompt = f"""
Ты парсер календарных событий для Telegram-бота.

Текущая дата и время по Москве: {now_text}.
Таймзона: Europe/Moscow.

Верни СТРОГО JSON без markdown и пояснений.

Если пользователь хочет добавить событие/встречу в календарь:
{{
  "action": "create_event",
  "title": "название события",
  "event_at": "YYYY-MM-DD HH:MM",
  "human_time": "человеческое описание времени"
}}

Если это не добавление события:
{{
  "action": "none"
}}

Понимай:
- встреча завтра в 12:00 созвон с клиентом
- бот, добавь в календарь завтра в 15:30 показ квартиры
- созвон сегодня в 18:00
- встреча в понедельник в 11:00 с клиентом
- 25.06 в 16:00 сделка

Если время не указано, верни action none.
Если дата уже прошла, выбери ближайшую будущую дату.
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
            try:
                return json.loads(clean_json(raw))
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
        "Открой меню командой /menu",
        reply_markup=main_menu()
    )


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Главное меню:",
        reply_markup=main_menu()
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


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    now = datetime.now(MOSCOW_TZ)

    if data == "main_menu":
        await query.edit_message_text("Главное меню:", reply_markup=main_menu())
        return

    if data == "tasks":
        await query.edit_message_text(
            format_tasks(get_open_tasks()) + "\n\nДобавить: бот, задача Катерине: проверить ДДУ\nЗакрыть: бот, закрой задачу 3",
            reply_markup=main_menu()
        )
        return

    if data == "clients":
        await query.edit_message_text(
            "👥 Клиенты пока следующий блок.\n\nСначала сделали меню и календарь. Следующим шагом добавим карточки клиентов.",
            reply_markup=main_menu()
        )
        return

    if data == "calendar":
        await query.edit_message_text("📅 Календарь:", reply_markup=calendar_menu())
        return

    if data == "calendar_today":
        date_str = now.strftime("%Y-%m-%d")
        await query.edit_message_text(
            f"📅 Сегодня, {now.strftime('%d.%m.%Y')}\n\n{format_events(get_events_for_day(date_str))}",
            reply_markup=calendar_menu()
        )
        return

    if data == "calendar_tomorrow":
        tomorrow = now + timedelta(days=1)
        date_str = tomorrow.strftime("%Y-%m-%d")
        await query.edit_message_text(
            f"📅 Завтра, {tomorrow.strftime('%d.%m.%Y')}\n\n{format_events(get_events_for_day(date_str))}",
            reply_markup=calendar_menu()
        )
        return

    if data == "calendar_week":
        await query.edit_message_text(
            format_events(get_events_for_next_days(7)),
            reply_markup=calendar_menu()
        )
        return

    if data == "calendar_add_help":
        await query.edit_message_text(
            "➕ Как добавить встречу:\n\n"
            "бот, встреча завтра в 12:00 созвон с клиентом\n"
            "бот, добавь в календарь сегодня в 18:30 показ квартиры\n"
            "бот, встреча в понедельник в 11:00 с клиентом\n\n"
            "Удалить встречу:\n"
            "бот, удали событие 3",
            reply_markup=calendar_menu()
        )
        return

    if data == "reminders":
        await query.edit_message_text(
            "🔔 Напоминания:\n\n"
            "Можно писать так:\n"
            "напомни через 15 минут позвонить клиенту\n"
            "напомни завтра в 10:00 проверить ипотеку\n"
            "бот, напомни Кате через час отправить договор",
            reply_markup=main_menu()
        )
        return

    if data == "memory":
        items = get_knowledge()
        if not items:
            text = "🧠 Память пока пустая."
        else:
            text = "🧠 Я помню:\n\n"
            for item_id, item_text in items:
                text += f"{item_id}. {item_text}\n"

        text += "\n\nДобавить: бот, запомни: важная информация\nУдалить: бот, забудь 3"
        await query.edit_message_text(text, reply_markup=main_menu())
        return


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

    if clean_lower.startswith("меню"):
        await update.message.reply_text("Главное меню:", reply_markup=main_menu())
        return

    # ПАМЯТЬ
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

    # КАЛЕНДАРЬ
    if (
        "расписание" in clean_lower
        or "календарь" in clean_lower
        or "встреча" in clean_lower
        or "созвон" in clean_lower
        or "показ" in clean_lower
        or "событие" in clean_lower
    ):
        if "расписание сегодня" in clean_lower or "календарь сегодня" in clean_lower:
            date_str = datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")
            await update.message.reply_text(format_events(get_events_for_day(date_str)))
            return

        if "расписание завтра" in clean_lower or "календарь завтра" in clean_lower:
            date_str = (datetime.now(MOSCOW_TZ) + timedelta(days=1)).strftime("%Y-%m-%d")
            await update.message.reply_text(format_events(get_events_for_day(date_str)))
            return

        if "расписание на неделю" in clean_lower or "календарь на неделю" in clean_lower:
            await update.message.reply_text(format_events(get_events_for_next_days(7)))
            return

        if clean_lower.startswith("удали событие"):
            match = re.search(r"\d+", clean_lower)
            if not match:
                await update.message.reply_text("Укажи номер события. Например: бот, удали событие 3")
                return
            delete_event(int(match.group()))
            await update.message.reply_text(f"✅ Событие {match.group()} удалено")
            return

        event_result = await analyze_event_with_ai(clean_text, sender)

        if event_result.get("action") == "create_event":
            title = event_result.get("title", "").strip()
            event_at = event_result.get("event_at", "").strip()
            human_time = event_result.get("human_time", event_at)

            if not title or not event_at:
                await update.message.reply_text("Не смогла понять название или время встречи.")
                return

            add_event(title, event_at, sender)

            await update.message.reply_text(
                f"✅ Добавила в календарь.\n\n{human_time}:\n{title}"
            )
            return

    # НАПОМИНАНИЯ
    if has_reminder_word:
        await update.message.chat.send_action("typing")
        reminder_result = await analyze_reminder_with_ai(user_text=user_text, sender=sender)

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
app.add_handler(CommandHandler("menu", menu))
app.add_handler(CommandHandler("id", my_id))
app.add_handler(CommandHandler("remind", remind))
app.add_handler(CallbackQueryHandler(button_handler))

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
