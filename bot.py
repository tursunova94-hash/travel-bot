import os, logging, json, asyncio, re
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

def load_skills():
    if not os.path.exists(SKILLS_FILE):
        return {"extra": ""}
    with open(SKILLS_FILE) as f:
        return json.load(f)

def save_skills(skills):
    with open(SKILLS_FILE, "w") as f:
        json.dump(skills, f, ensure_ascii=False, indent=2)

def parse_json_from_reply(text):
    try:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
    except:
        pass
    return {}

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

ПОИСК:
Когда нужна актуальная информация — используй веб-поиск автоматически.

КАЛЕНДАРЬ:
Когда просят создать встречу — в конце ответа добавь:
CALENDAR:{"title":"название","date":"2026-04-10T15:00:00+05:00","description":"описание"}

ПОЧТА ОТПРАВКА:
Когда просят отправить письмо — в конце ответа добавь:
EMAIL:{"to":"адрес@gmail.com","subject":"тема","body":"текст письма в одну строку без переносов"}

ПОЧТА ЧТЕНИЕ:
Когда просят показать письма — в конце ответа добавь:
READ_EMAIL:{"max_results":5,"query":"поисковый запрос если нужен"}

ОТВЕТ НА ПИСЬМО:
Когда нужно ответить на письмо — добавь в конце:
REPLY_EMAIL:{"message_id":"ID_письма","body":"текст ответа в одну строку"}

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
            logging.info(f"Make response: {r.status_code} {r.text}")
    except Exception as e:
        logging.error(f"Calendar error: {e}")

async def send_email(data):
    if not MAKE_GMAIL_WEBHOOK:
        return
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(MAKE_GMAIL_WEBHOOK, json=data, timeout=15)
            logging.info(f"Gmail response: {r.status_code} {r.text}")
    except Exception as e:
        logging.error(f"Gmail error: {e}")

def get_gmail_service():
    import pickle
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    token_path = os.path.join(os.path.dirname(__file__), 'token.pickle')
    if not os.path.exists(token_path):
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

def read_emails(max_results=5, query=""):
    service = get_gmail_service()
    if not service:
        return "Gmail не подключён"
    try:
        params = {"userId": "me", "maxResults": max_results}
        if query:
            params["q"] = query
        else:
            params["labelIds"] = ["INBOX"]
        results = service.users().messages().list(**params).execute()
        messages = results.get("messages", [])
        if not messages:
            return "Писем нет"
        emails = []
        for msg in messages[:max_results]:
            m = service.users().messages().get(userId="me", id=msg["id"], format="full").execute()
            headers = {h["name"]: h["value"] for h in m["payload"]["headers"]}
            emails.append(f"ID: {msg['id']}\nОт: {headers.get('From', '')}\nТема: {headers.get('Subject', '')}\n{m.get('snippet', '')[:200]}")
        return "\n\n---\n\n".join(emails)
    except Exception as e:
        logging.error(f"Read email error: {e}")
        return f"Ошибка: {e}"

def reply_to_email(message_id: str, body: str):
    service = get_gmail_service()
    if not service:
        return "Gmail не подключён"
    try:
        import base64
        from email.mime.text import MIMEText
        original = service.users().messages().get(userId="me", id=message_id, format="full").execute()
        headers = {h["name"]: h["value"] for h in original["payload"]["headers"]}
        to = headers.get("From", "")
        subject = headers.get("Subject", "")
        if not subject.startswith("Re:"):
            subject = f"Re: {subject}"
        thread_id = original["threadId"]
        msg = MIMEText(body)
        msg["to"] = to
        msg["subject"] = subject
        msg["In-Reply-To"] = headers.get("Message-ID", "")
        msg["References"] = headers.get("Message-ID", "")
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw, "threadId": thread_id}).execute()
        return f"Ответ отправлен на {to}"
    except Exception as e:
        logging.error(f"Reply email error: {e}")
        return f"Ошибка: {e}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories[user_id] = []
    await update.message.reply_text("Привет! Я Амелия, ваш личный ассистент ✨\n\nПомогу с турами, письмами, календарём, поиском — всем!\n\nЧем могу помочь?")

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
            max_tokens=2000,
            system=get_system_prompt(),
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=user_histories[user_id]
        )
        reply = ""
        for block in response.content:
            if hasattr(block, "text"):
                reply += block.text

        if not reply:
            reply = "Готово! Если нужно что-то ещё — спрашивай."

        user_histories[user_id].append({"role": "assistant", "content": reply})

        if "CALENDAR:" in reply:
            parts = reply.split("CALENDAR:")
            clean_reply = parts[0].strip()
            try:
                cal_data = parse_json_from_reply(parts[1])
                await create_calendar_event(cal_data)
                clean_reply += "\n\n✅ Событие добавлено в календарь!"
            except Exception as e:
                logging.error(f"Calendar parse error: {e}")
                clean_reply = reply
            await update.message.reply_text(clean_reply)

        elif "READ_EMAIL:" in reply:
            parts = reply.split("READ_EMAIL:")
            clean_reply = parts[0].strip()
            try:
                params = parse_json_from_reply(parts[1])
                emails = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: read_emails(params.get("max_results", 5), params.get("query", ""))
                )
                clean_reply += f"\n\n📧 Письма:\n\n{emails}"
            except Exception as e:
                logging.error(f"Read email parse error: {e}")
                clean_reply = reply
            await update.message.reply_text(clean_reply)

        elif "REPLY_EMAIL:" in reply:
            parts = reply.split("REPLY_EMAIL:")
            clean_reply = parts[0].strip()
            try:
                params = parse_json_from_reply(parts[1])
                result = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: reply_to_email(params.get("message_id", ""), params.get("body", ""))
                )
                clean_reply += f"\n\n✅ {result}"
            except Exception as e:
                logging.error(f"Reply email parse error: {e}")
                clean_reply = reply
            await update.message.reply_text(clean_reply)

        elif "EMAIL:" in reply:
            parts = reply.split("EMAIL:")
            clean_reply = parts[0].strip()
            try:
                email_data = parse_json_from_reply(parts[1])
                await send_email(email_data)
                clean_reply += "\n\n✅ Письмо отправлено!"
            except Exception as e:
                logging.error(f"Email parse error: {e}")
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
