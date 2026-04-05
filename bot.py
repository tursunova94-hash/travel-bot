import os
import logging
import json
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, MessageHandler,
    CommandHandler, filters, ContextTypes
)
import anthropic

load_dotenv()
logging.basicConfig(level=logging.INFO)

claude = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY").strip())

user_histories = {}
SKILLS_FILE = "skills.json"
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

def load_skills():
    if not os.path.exists(SKILLS_FILE):
        return {"extra": ""}
    with open(SKILLS_FILE) as f:
        return json.load(f)

def save_skills(skills):
    with open(SKILLS_FILE, "w") as f:
        json.dump(skills, f, ensure_ascii=False, indent=2)

def get_system_prompt():
    skills = load_skills()
    base = """Ты — Амелия, личный ИИ-ассистент владелицы турагентства премиум класса.
Ты умеешь абсолютно всё:

ТУРИЗМ:
- Подбор туров (Турция, Мальдивы, Азия, Стамбул, Бодрум, Анталия)
- Сравнение операторов и цен
- Составление подборок для клиентов
- Переговоры с ДМС и операторами

БИЗНЕС:
- Составление писем и emails на русском, английском, турецком
- Анализ данных и таблиц
- Планирование задач и встреч
- Протоколы звонков и встреч

ОБЩЕЕ:
- Помощь с любыми вопросами
- Поиск информации
- Советы и рекомендации

Отвечай по-русски, тепло и профессионально.
Ты — умный, преданный помощник который знает всё о бизнесе хозяйки."""

    if skills.get("extra"):
        base += f"\n\nДОПОЛНИТЕЛЬНЫЕ УМЕЛКИ:\n{skills['extra']}"
    return base

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories[user_id] = []
    await update.message.reply_text(
        "Привет! Я Амелия, ваш личный ассистент ✨\n\n"
        "Помогу с турами, письмами, таблицами, планированием — всем!\n\n"
        "Чем могу помочь?"
    )

async def add_skill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if OWNER_ID and user_id != OWNER_ID:
        await update.message.reply_text("Только владелец может добавлять умелки.")
        return
    if not context.args:
        await update.message.reply_text(
            "Использование: /addskill описание умелки\n\n"
            "Например: /addskill Знаешь цены отеля Rixos наизусть"
        )
        return
    skill_text = " ".join(context.args)
    skills = load_skills()
    if skills.get("extra"):
        skills["extra"] += f"\n- {skill_text}"
    else:
        skills["extra"] = f"- {skill_text}"
    save_skills(skills)
    await update.message.reply_text(f"✅ Умелка добавлена:\n{skill_text}")

async def list_skills(update: Update, context: ContextTypes.DEFAULT_TYPE):
    skills = load_skills()
    if not skills.get("extra"):
        await update.message.reply_text("Пока нет дополнительных умелок.")
        return
    await update.message.reply_text(f"📋 Мои умелки:\n{skills['extra']}")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories[user_id] = []
    await update.message.reply_text("Начинаем сначала! ✨")

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
            max_tokens=1500,
            system=get_system_prompt(),
            messages=user_histories[user_id]
        )
        reply = response.content[0].text
        user_histories[user_id].append({"role": "assistant", "content": reply})
        await update.message.reply_text(reply)

    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await update.message.reply_text("Что-то пошло не так 🙏")

app = ApplicationBuilder().token(os.getenv("TELEGRAM_TOKEN").strip()).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("reset", reset))
app.add_handler(CommandHandler("addskill", add_skill))
app.add_handler(CommandHandler("skills", list_skills))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("✅ Бот запущен!")
app.run_polling()
