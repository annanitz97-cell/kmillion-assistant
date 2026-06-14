import os
import aiohttp
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.getenv("BOT_TOKEN")
AITUNNEL_API_KEY = os.getenv("AITUNNEL_API_KEY")
MODEL = os.getenv("MODEL", "gpt-4.1-mini")


async def ask_ai(message: str):
    url = "https://api.aitunnel.ru/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {AITUNNEL_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": """
Ты KMillion Assistant.

Ты помогаешь двум партнерам агентства недвижимости.

Твои задачи:
- отвечать на вопросы
- помогать с недвижимостью
- помогать с контентом
- помогать с организацией работы
- давать краткие и понятные ответы
"""
            },
            {
                "role": "user",
                "content": message
            }
        ]
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            headers=headers,
            json=payload
        ) as response:

            data = await response.json()

            return data["choices"][0]["message"]["content"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я KMillion Assistant 🚀"
    )


async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user_text = update.message.text

    await update.message.chat.send_action("typing")

    try:
        answer = await ask_ai(user_text)

        await update.message.reply_text(answer)

    except Exception as e:
        await update.message.reply_text(
            f"Ошибка: {str(e)}"
        )


app = Application.builder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message
    )
)

app.run_polling()
