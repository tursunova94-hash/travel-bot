import os, logging, json
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
import anthropic, httpx

load_dotenv()
logging.basicConfig(level=logging.INFO)

claude = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY").strip())
user_histories = {}
SKILLS_FILE = "skills.json"
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
MAKE_WEBHOOK = os.getenv("MAKE_WEBHOOK", "")

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

ТУРИЗМ:
- Подбор туров (Турция, Мальдивы, Азия, Стамбул, Бодрум, Анталия)
- Сравнение операторов и цен
- Составление подборок для клиентов
- Переговоры с ДМС и операторами

БИЗНЕС:
- Составление писем на русском, английском, турецком
- Анализ данных и таблиц
- Планирование задач и встреч

КАЛЕНДАРЬ:
Когда просят создать встречу — в конце ответа добавь:
CALENDAR:{"title":"название","date":"2026-04-07T18:00:00","description":"описание"}
Формат даты ВСЕГДА ISO с часовым поясом Ташкента: ГГГГ-ММ-ДДTЧЧ:ММ:СС+05:00
Например встреча 10 апреля в 15:00 = 2026-04-10T15:00:00+05:00
Сегодня 2026-04-05.

Отвечай по-русски, тепло и профессионально."""

    if skills.get("extra"):
        base += f"\n\nДОПОЛНИТЕЛЬНЫЕ УМЕЛКИ:\n{skills['extra']}"
    return base

async def create_calendar_event(data):
    if not MAKE_WEBHOOK:
        logging.warning("MAKE_WEBHOOK not set!")
        return
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(MAKE_WEBHOOK, json=data, timeout=15)
            logging.info(f"Make response: {r.status_code} {r.text}")
    except Exception as e:
        logging.error(f"Calendar error: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories[user_id] = []
    await update.message.reply_text("Привет! Я Амелия ✨\nЧем могу помочь?")

async def add_skill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if OWNER_ID and user_id != OWNER_ID:
        await update.message.reply_text("Только владелец может добавлять умелки.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /addskill описание")
        return
    skill_text = " ".join(context.args)
    skills = load_skills()
    skills["extra"] = skills.get("extra", "") + f"\n- {skill_text}"
    save_skills(skills)
    await update.message.reply_text(f"✅ Умелка добавлена: {skill_text}")

async def list_skills(update: Update, context: ContextTypes.DEFAULT_TYPE):
    skills = load_skills()
    if not skills.get("extra"):
        await update.message.reply_text("Пока нет умелок.")
        return
    await update.message.reply_text(f"📋 Умелки:\n{skills['extra']}")

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_histories[update.effective_user.id] = []
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
        if "CALENDAR:" in reply:
            parts = reply.split("CALENDAR:")
            clean_reply = parts[0].strip()
            try:
                cal_data = json.loads(parts[1].strip())
                await create_calendar_event(cal_data)
                clean_reply += "\n\n✅ Событие добавлено в календарь!"
            except Exception as e:
                logging.error(f"Parse error: {e}")
                clean_reply = reply
            await update.message.reply_text(clean_reply)
        else:
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
