import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, MessageHandler,
    CommandHandler, filters, ContextTypes
)
import anthropic

load_dotenv()
logging.basicConfig(level=logging.INFO)

claude = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

user_histories = {}

SYSTEM_PROMPT = """Ты — личный ИИ-ассистент турагентства премиум класса.
Специализация: Турция (Анталия, Бодрум, Стамбул), Мальдивы, Азия (Сингапур, Малайзия).

Когда пишет клиент — тепло и профессионально выясняй:
- Направление
- Даты и количество ночей
- Количество человек, есть ли дети
- Бюджет
- Пожелания (релакс/экскурсии, уровень отеля)

Когда пишет владелец агентства — помогай с:
- Анализом цен и операторов
- Письмами операторам и ДМС
- Подборками для клиентов
- Переговорами с новыми партнёрами

Отвечай по-русски. Ты лучший помощник в турбизнесе."""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories[user_id] = []
    await update.message.reply_text(
        "Привет! Я ваш персональный тревел-ассистент ✈️\n\n"
        "Расскажите — куда мечтаете отправиться?"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_text = update.message.text

    if user_id not in user_histories:
        user_histories[user_id] = []

    user_histories[user_id].append({"role": "user", "content": user_text})

    if len(user_histories[user_id]) > 20:
        user_histories[user_id] = user_histories[user_id][-20:]

    await update.message.reply_text("⏳")

    try:
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=user_histories[user_id]
        )
        reply = response.content[0].text
        user_histories[user_id].append({"role": "assistant", "content": reply})
        await update.message.reply_text(reply)

    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await update.message.reply_text("Что-то пошло не так, попробуйте ещё раз 🙏")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories[user_id] = []
    await update.message.reply_text("Начинаем сначала! Чем могу помочь? ✈️")

app = ApplicationBuilder().token(os.getenv("TELEGRAM_TOKEN").strip()).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("reset", reset))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
print("✅ Бот запущен!")
app.run_polling()


