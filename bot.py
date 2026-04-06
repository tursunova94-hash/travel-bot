import os, logging, json, asyncio
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
MAKE_GMAIL_WEBHOOK = os.getenv("MAKE_GMAIL_WEBHOOK", "")
GMAIL_TOKEN_B64 = os.getenv("GMAIL_TOKEN", "")

def load_skills():
    if not os.path.exists(SKILLS_FILE):
        return {"extra": ""}
    with open(SKILLS_FILE) as f:
        return json.load(f)

def save_skills(skills):
    with open(SKILLS_FILE, "w") as f:
        json.dump(skills, f, ensure_ascii=False, indent=2)

def get_gmail_service():
    import pickle
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    
    token_path = os.path.join(os.path.dirname(__file__), 'token.pickle')
    if not os.path.exists(token_path):
        logging.error("token.pickle not found!")
        return None
    try:
        with open(token_path, 'rb') as f:
            creds = pickle.load(f)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return build('gmail', 'v1', credentials=creds)
    except Exception as e:
        logging.error(f"Gmail service error: {e}")
        return None

def read_emails_sync(max_results=5, query=""):
    service = get_gmail_service()
    if not service:
        return "Gmail не подключён"
    try:
        params = {"userId": "me", "maxResults": max_results, "labelIds": ["INBOX"]}
        if query:
            params["q"] = query
        results = service.users().messages().list(**params).execute()
        messages = results.get("messages", [])
        if not messages:
            return "Входящих писем нет"
        emails = []
        for msg in messages[:max_results]:
            m = service.users().messages().get(userId="me", id=msg["id"], format="full").execute()
            headers = {h["name"]: h["value"] for h in m["payload"]["headers"]}
            emails.append(f"От: {headers.get('From', '')}\nТема: {headers.get('Subject', '')}\n{m.get('snippet', '')[:200]}")
        return "\n\n---\n\n".join(emails)
    except Exception as e:
        logging.error(f"Read email error: {e}")
        return f"Ошибка: {e}"

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
CALENDAR:{"title":"название","date":"2026-04-10T15:00:00+05:00","description":"описание"}
Формат даты ВСЕГДА ISO с часовым поясом: ГГГГ-ММ-ДДTЧЧ:ММ:СС+05:00
Сегодня 2026-04-05.

ПОЧТА ИСХОДЯЩАЯ:
Когда просят отправить письмо — в конце ответа добавь:
EMAIL:{"to":"адрес@gmail.com","subject":"тема","body":"текст письма"}

ПОЧТА ВХОДЯЩАЯ:
Когда просят показать письма или найти письмо от кого-то — в конце ответа добавь:
READ_EMAIL:{"max_results":5,"query":"поисковый запрос"}
Например если ищут письма от Asialuxe: READ_EMAIL:{"max_results":5,"query":"from:asialuxe"}

Отвечай по-русски, тепло и профессионально."""
    if skills.get("extra"):
        base += f"\n\nДОПОЛНИТЕЛЬНЫЕ УМЕЛКИ:\n{skills['extra']}"
    return base

async def create_calendar_event(data):
    if not MAKE_WEBHOOK:
        return
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(MAKE_WEBHOOK, json=data, timeout=15)
            logging.info(f"Make response: {r.status_code}")
    except Exception as e:
        logging.error(f"Calendar error: {e}")

async def send_email(data):
    if not MAKE_GMAIL_WEBHOOK:
        return
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(MAKE_GMAIL_WEBHOOK, json=data, timeout=15)
            logging.info(f"Gmail response: {r.status_code}")
    except Exception as e:
        logging.error(f"Gmail error: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories[user_id] = []
    await update.message.reply_text(
        "Привет! Я Амелия, ваш личный ассистент ✨\n\n"
        "Помогу с турами, письмами, календарём — всем!\n\n"
        "Чем могу помочь?"
    )

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
                logging.error(f"Calendar parse error: {e}")
                clean_reply = reply
            await update.message.reply_text(clean_reply)
        elif "EMAIL:" in reply and "READ_EMAIL:" not in reply:
            parts = reply.split("EMAIL:")
            clean_reply = parts[0].strip()
            try:
                email_data = json.loads(parts[1].strip())
                await send_email(email_data)
                clean_reply += "\n\n✅ Письмо отправлено!"
            except Exception as e:
                logging.error(f"Email parse error: {e}")
                clean_reply = reply
            await update.message.reply_text(clean_reply)
        elif "READ_EMAIL:" in reply:
            parts = reply.split("READ_EMAIL:")
            clean_reply = parts[0].strip()
            try:
                params = json.loads(parts[1].strip())
                loop = asyncio.get_event_loop()
                emails = await loop.run_in_executor(
                    None,
                    lambda: read_emails_sync(
                        params.get("max_results", 5),
                        params.get("query", "")
                    )
                )
                clean_reply += f"\n\n📧 Письма:\n\n{emails}"
            except Exception as e:
                logging.error(f"Read email parse error: {e}")
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
