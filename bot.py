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

def extract_all_blocks(reply, tag):
    pattern = rf'{tag}:(\{{[^}}]*\}})'
    matches = re.findall(pattern, reply, re.DOTALL)
    result = []
    for m in matches:
        try:
            result.append(json.loads(m))
        except:
            try:
                result.append(parse_json_from_reply(m))
            except:
                pass
    return result

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

ПОЧТА ОТПРАВКА (можно несколько):
Когда просят отправить письма — добавь для каждого:
EMAIL:{"to":"адрес1@gmail.com","subject":"тема1","body":"текст1"}
EMAIL:{"to":"адрес2@gmail.com","subject":"тема2","body":"текст2"}

ПОЧТА ЧТЕНИЕ:
READ_EMAIL:{"max_results":5,"query":"поисковый запрос если нужен"}

ОТВЕТ НА ПИСЬМО:
REPLY_EMAIL:{"message_id":"ID_письма","body":"текст ответа"}

GOOGLE SHEETS — СОЗДАТЬ:
CREATE_SHEET:{"title":"название","headers":["Колонка1","Колонка2"]}

GOOGLE SHEETS — ДОБАВИТЬ СТРОКУ:
ADD_ROW:{"sheet_url":"ссылка","row":["значение1","значение2"]}

GOOGLE SHEETS — ЧИТАТЬ:
READ_SHEET:{"sheet_url":"ссылка","limit":10}

GOOGLE SHEETS — ОБНОВИТЬ ЯЧЕЙКУ:
UPDATE_CELL:{"sheet_url":"ссылка","row":2,"col":3,"value":"новое значение"}

GOOGLE SHEETS — НАЙТИ И ОБНОВИТЬ СТРОКУ:
UPDATE_ROW:{"sheet_url":"ссылка","search_col":1,"search_value":"что ищем","updates":{"2":"значение","5":"значение"}}

GOOGLE SHEETS — ФОРМАТИРОВАТЬ:
FORMAT_SHEET:{"sheet_url":"ссылка"}

Отвечай по-русски, тепло и профессионально."""
    if skills.get("extra"):
        base += f"\n\nДОПОЛНИТЕЛЬНЫЕ УМЕЛКИ:\n{skills['extra']}"
    return base

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

def get_sheets_client():
    import pickle
    import gspread
    from google.auth.transport.requests import Request
    token_path = os.path.join(os.path.dirname(__file__), 'token.pickle')
    if not os.path.exists(token_path):
        return None
    try:
        with open(token_path, 'rb') as f:
            creds = pickle.load(f)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return gspread.authorize(creds)
    except Exception as e:
        logging.error(f"Sheets client error: {e}")
        return None

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
    to = data.get("to", "")
    subject = data.get("subject", "")
    body = data.get("body", "")
    service = get_gmail_service()
    if service:
        try:
            import base64
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText
            msg = MIMEMultipart('alternative')
            msg["to"] = to
            msg["subject"] = subject
            html_body = body.replace('\\n', '<br>').replace('\n', '<br>')
            html = f"<html><body><p>{html_body}</p></body></html>"
            msg.attach(MIMEText(body, 'plain'))
            msg.attach(MIMEText(html, 'html'))
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            service.users().messages().send(userId="me", body={"raw": raw}).execute()
            logging.info(f"Email sent to {to}")
            return True
        except Exception as e:
            logging.error(f"Direct Gmail error: {e}")
    if MAKE_GMAIL_WEBHOOK:
        try:
            async with httpx.AsyncClient() as client:
                await client.post(MAKE_GMAIL_WEBHOOK, json=data, timeout=15)
            return True
        except Exception as e:
            logging.error(f"Gmail Make error: {e}")
    return False

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

def create_sheet(title: str, headers: list):
    gc = get_sheets_client()
    if not gc:
        return None, "Google Sheets не подключён"
    try:
        sh = gc.create(title)
        ws = sh.get_worksheet(0)
        ws.append_row(headers)
        sh.share(None, perm_type='anyone', role='writer')
        return sh.url, f"Таблица '{title}' создана!"
    except Exception as e:
        logging.error(f"Create sheet error: {e}")
        return None, f"Ошибка: {e}"

def add_row_to_sheet(sheet_url: str, row: list):
    gc = get_sheets_client()
    if not gc:
        return "Google Sheets не подключён"
    try:
        sh = gc.open_by_url(sheet_url)
        ws = sh.get_worksheet(0)
        ws.append_row(row)
        return "Строка добавлена!"
    except Exception as e:
        logging.error(f"Add row error: {e}")
        return f"Ошибка: {e}"

def read_sheet(sheet_url: str, limit: int = 10):
    gc = get_sheets_client()
    if not gc:
        return "Google Sheets не подключён"
    try:
        sh = gc.open_by_url(sheet_url)
        ws = sh.get_worksheet(0)
        data = ws.get_all_values()
        if not data:
            return "Таблица пустая"
        result = []
        for row in data[:limit]:
            result.append(" | ".join(row))
        return "\n".join(result)
    except Exception as e:
        logging.error(f"Read sheet error: {e}")
        return f"Ошибка: {e}"

def update_cell(sheet_url: str, row: int, col: int, value: str):
    gc = get_sheets_client()
    if not gc:
        return "Google Sheets не подключён"
    try:
        sh = gc.open_by_url(sheet_url)
        ws = sh.get_worksheet(0)
        ws.update_cell(row, col, value)
        return f"Ячейка ({row},{col}) обновлена!"
    except Exception as e:
        logging.error(f"Update cell error: {e}")
        return f"Ошибка: {e}"

def update_row(sheet_url: str, search_col: int, search_value: str, updates: dict):
    gc = get_sheets_client()
    if not gc:
        return "Google Sheets не подключён"
    try:
        sh = gc.open_by_url(sheet_url)
        ws = sh.get_worksheet(0)
        col_values = ws.col_values(search_col)
        if search_value not in col_values:
            return f"Строка с '{search_value}' не найдена"
        row_num = col_values.index(search_value) + 1
        for col_str, value in updates.items():
            ws.update_cell(row_num, int(col_str), value)
        return f"Строка '{search_value}' обновлена!"
    except Exception as e:
        logging.error(f"Update row error: {e}")
        return f"Ошибка: {e}"

def format_sheet(sheet_url: str):
    gc = get_sheets_client()
    if not gc:
        return "Google Sheets не подключён"
    try:
        sh = gc.open_by_url(sheet_url)
        ws = sh.get_worksheet(0)
        ws.freeze(rows=1)
        ws.format("1:1", {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.2, "green": 0.6, "blue": 0.9}
        })
        ws.set_basic_filter()
        return "Таблица отформатирована!"
    except Exception as e:
        logging.error(f"Format sheet error: {e}")
        return f"Ошибка: {e}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_histories[user_id] = []
    await update.message.reply_text("Привет! Я Амелия, ваш личный ассистент ✨\n\nПомогу с турами, письмами, календарём, таблицами — всем!\n\nЧем могу помочь?")

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

        # Определяем какие команды есть в ответе
        has_calendar = "CALENDAR:" in reply
        has_email = "EMAIL:" in reply
        has_read_email = "READ_EMAIL:" in reply
        has_reply_email = "REPLY_EMAIL:" in reply
        has_create_sheet = "CREATE_SHEET:" in reply
        has_add_row = "ADD_ROW:" in reply
        has_read_sheet = "READ_SHEET:" in reply
        has_update_cell = "UPDATE_CELL:" in reply
        has_update_row = "UPDATE_ROW:" in reply
        has_format_sheet = "FORMAT_SHEET:" in reply

        if has_calendar:
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

        elif has_read_email:
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

        elif has_reply_email:
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

        elif has_email:
            # Поддержка нескольких писем
            email_blocks = re.findall(r'EMAIL:\{[^}]*\}', reply, re.DOTALL)
            clean_reply = re.sub(r'EMAIL:\{[^}]*\}', '', reply, flags=re.DOTALL).strip()
            sent = 0
            for block in email_blocks:
                try:
                    email_data = parse_json_from_reply(block.replace("EMAIL:", ""))
                    if email_data.get("to"):
                        await send_email(email_data)
                        sent += 1
                except Exception as e:
                    logging.error(f"Email send error: {e}")
            if sent > 0:
                clean_reply += f"\n\n✅ Отправлено писем: {sent}"
            await update.message.reply_text(clean_reply)

        elif has_create_sheet:
            parts = reply.split("CREATE_SHEET:")
            clean_reply = parts[0].strip()
            try:
                params = parse_json_from_reply(parts[1])
                url, msg = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: create_sheet(params.get("title", "Таблица"), params.get("headers", []))
                )
                clean_reply += f"\n\n✅ {msg}\n📊 {url}" if url else f"\n\n❌ {msg}"
            except Exception as e:
                logging.error(f"Create sheet error: {e}")
                clean_reply = reply
            await update.message.reply_text(clean_reply)

        elif has_add_row:
            parts = reply.split("ADD_ROW:")
            clean_reply = parts[0].strip()
            try:
                params = parse_json_from_reply(parts[1])
                result = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: add_row_to_sheet(params.get("sheet_url", ""), params.get("row", []))
                )
                clean_reply += f"\n\n✅ {result}"
            except Exception as e:
                logging.error(f"Add row error: {e}")
                clean_reply = reply
            await update.message.reply_text(clean_reply)

        elif has_read_sheet:
            parts = reply.split("READ_SHEET:")
            clean_reply = parts[0].strip()
            try:
                params = parse_json_from_reply(parts[1])
                data = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: read_sheet(params.get("sheet_url", ""), params.get("limit", 10))
                )
                clean_reply += f"\n\n📊 Данные:\n\n{data}"
            except Exception as e:
                logging.error(f"Read sheet error: {e}")
                clean_reply = reply
            await update.message.reply_text(clean_reply)

        elif has_update_cell:
            parts = reply.split("UPDATE_CELL:")
            clean_reply = parts[0].strip()
            try:
                params = parse_json_from_reply(parts[1])
                result = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: update_cell(
                        params.get("sheet_url", ""),
                        params.get("row", 1),
                        params.get("col", 1),
                        params.get("value", "")
                    )
                )
                clean_reply += f"\n\n✅ {result}"
            except Exception as e:
                logging.error(f"Update cell error: {e}")
                clean_reply = reply
            await update.message.reply_text(clean_reply)

        elif has_update_row:
            parts = reply.split("UPDATE_ROW:")
            clean_reply = parts[0].strip()
            try:
                params = parse_json_from_reply(parts[1])
                result = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: update_row(
                        params.get("sheet_url", ""),
                        params.get("search_col", 1),
                        params.get("search_value", ""),
                        params.get("updates", {})
                    )
                )
                clean_reply += f"\n\n✅ {result}"
            except Exception as e:
                logging.error(f"Update row error: {e}")
                clean_reply = reply
            await update.message.reply_text(clean_reply)

        elif has_format_sheet:
            parts = reply.split("FORMAT_SHEET:")
            clean_reply = parts[0].strip()
            try:
                params = parse_json_from_reply(parts[1])
                result = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: format_sheet(params.get("sheet_url", ""))
                )
                clean_reply += f"\n\n✅ {result}"
            except Exception as e:
                logging.error(f"Format sheet error: {e}")
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
