"""
Telegram-бот «Анкета + Статистика».
Создаём мини-опрос с сохранением в SQLite и даём пользователю удобное меню:
- Пройти анкету
- Статистика
- Последние ответы
- Экспорт CSV
- Удалить мои данные
- Справка

Технологии:
- python-telegram-bot==21.4 (асинхронный PTB v21)
- SQLite в файле survey.db
- .env для хранения TELEGRAM_BOT_TOKEN

Как запустить:
1) python -m venv venv && (venv\Scripts\activate) / (source venv/bin/activate)
2) pip install python-telegram-bot==21.4 python-dotenv==1.0.1
3) создать .env с TELEGRAM_BOT_TOKEN=...
4) python bot.py
"""

import os
import io
import csv
import logging
import sqlite3
from datetime import datetime
from typing import Optional, Dict, List, Tuple

from dotenv import load_dotenv
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InputFile,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ------------------------- ЛОГИРОВАНИЕ -------------------------
logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("survey-bot")

# ------------------------- КОНСТАНТЫ / НАСТРОЙКИ -------------------------
DB_PATH = "survey.db"
TABLE_SQL = """
CREATE TABLE IF NOT EXISTS respondents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_user_id INTEGER,
    tg_username TEXT,
    q_name TEXT,
    q_age INTEGER,
    q_city TEXT,
    q_stack TEXT,
    q_consent INTEGER,
    created_at TEXT
);
"""

# Создаёт таблицу, если её нет (безопасно вызывать многократно)
def ensure_table_exists() -> None:
    conn = connect_db()
    try:
        conn.execute(TABLE_SQL)
        conn.commit()
    finally:
        conn.close()

# Состояния диалога. У нас есть "меню" и 5 шагов анкеты
MENU, Q_NAME, Q_AGE, Q_CITY, Q_STACK, Q_CONSENT = range(6)

# Варианты ответов
STACK_OPTIONS = ["Никогда", "Новичок", "1–3 года", "3+ лет"]
CONSENT_OPTIONS = ["Да", "Нет"]

# Текстовые ярлыки для кнопок меню (чтобы удобно сравнивать)
BTN_SURVEY = "📝 Пройти анкету"
BTN_STATS = "📊 Статистика"
BTN_LAST = "🗂 Последние ответы"
BTN_EXPORT = "📤 Экспорт CSV"
BTN_DELETE_ME = "🗑 Удалить мои данные"
BTN_HELP = "❓ Справка"

MENU_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton(BTN_SURVEY)],
        [KeyboardButton(BTN_STATS), KeyboardButton(BTN_LAST)],
        [KeyboardButton(BTN_EXPORT), KeyboardButton(BTN_DELETE_ME)],
        [KeyboardButton(BTN_HELP)],
    ],
    resize_keyboard=True,
)

# ------------------------- РАБОТА С БАЗОЙ -------------------------
def connect_db() -> sqlite3.Connection:
    """Открываем соединение с БД. В простом боте нам хватает синхронного sqlite3."""
    return sqlite3.connect(DB_PATH)

def init_db() -> None:
    """Создаём таблицу при первом запуске."""
    conn = connect_db()
    try:
        conn.execute(TABLE_SQL)
        conn.commit()
    finally:
        conn.close()

def insert_row(
    tg_user_id: int,
    tg_username: Optional[str],
    q_name: str,
    q_age: int,
    q_city: str,
    q_stack: str,
    q_consent: bool,
) -> None:
    """Добавляем запись анкеты."""
    conn = connect_db()
    try:
        conn.execute(
            """
            INSERT INTO respondents (
                tg_user_id, tg_username, q_name, q_age, q_city, q_stack, q_consent, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tg_user_id,
                tg_username,
                q_name,
                q_age,
                q_city,
                q_stack,
                1 if q_consent else 0,
                datetime.utcnow().isoformat(timespec="seconds") + "Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()

def count_rows() -> int:
    """Сколько всего записей в БД."""
    conn = connect_db()
    try:
        (n,) = conn.execute("SELECT COUNT(*) FROM respondents;").fetchone()
        return int(n)
    finally:
        conn.close()

def get_last_rows(limit: int = 10) -> List[Tuple]:
    """Последние N записей. Если таблицы ещё нет — создаём и возвращаем пустой список."""
    conn = connect_db()
    try:
        try:
            rows = conn.execute(
                """
                SELECT id, tg_username, q_name, q_age, q_city, q_stack, q_consent, created_at
                FROM respondents
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return rows
        except sqlite3.OperationalError:
            # таблицы нет -> создаём и возвращаем пусто
            return []
    finally:
        conn.close()


def get_stats() -> Dict[str, object]:
    """
    Безопасная статистика:
    - если таблицы ещё нет, создаём её и возвращаем "пустые" метрики.
    """
    try:
        conn = connect_db()
        try:
            # гарантируем, что таблица существует
            conn.execute("SELECT 1 FROM respondents LIMIT 1;")
        except sqlite3.OperationalError:
            # таблицы нет -> создаём и отдаём пустую статистику
            conn.close()
            ensure_table_exists()
            return {
                "total": 0,
                "avg_age": None,
                "min_age": None,
                "max_age": None,
                "by_stack": {},
                "top_cities": [],
                "consent_rate": None,
            }

        # --- обычные запросы статистики ---
        total, avg_age, min_age, max_age = conn.execute(
            """
            SELECT COUNT(*), AVG(q_age), MIN(q_age), MAX(q_age)
            FROM respondents
            WHERE q_age IS NOT NULL
            """
        ).fetchone()

        by_stack_rows = conn.execute(
            """
            SELECT q_stack, COUNT(*) as cnt
            FROM respondents
            WHERE q_stack IS NOT NULL
            GROUP BY q_stack
            ORDER BY cnt DESC
            """
        ).fetchall()
        by_stack = {k if k is not None else "—": int(v) for k, v in by_stack_rows}

        top_cities = conn.execute(
            """
            SELECT q_city, COUNT(*) as cnt
            FROM respondents
            WHERE q_city IS NOT NULL AND TRIM(q_city) <> ''
            GROUP BY q_city
            ORDER BY cnt DESC, q_city ASC
            LIMIT 5
            """
        ).fetchall()

        consent = conn.execute(
            """
            SELECT AVG(CAST(q_consent AS FLOAT))
            FROM respondents
            WHERE q_consent IN (0,1)
            """
        ).fetchone()[0]
        consent_rate = float(consent) if consent is not None else None

        return {
            "total": int(total or 0),
            "avg_age": float(avg_age) if avg_age is not None else None,
            "min_age": int(min_age) if min_age is not None else None,
            "max_age": int(max_age) if max_age is not None else None,
            "by_stack": by_stack,
            "top_cities": [(c or "—", int(n)) for c, n in top_cities],
            "consent_rate": consent_rate,
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass

def export_csv_bytes() -> bytes:
    """Выгружаем всю таблицу в CSV, возвращаем как bytes для отправки в Telegram."""
    conn = connect_db()
    try:
        rows = conn.execute(
            """
            SELECT id, tg_user_id, tg_username, q_name, q_age, q_city, q_stack, q_consent, created_at
            FROM respondents
            ORDER BY id ASC
            """
        ).fetchall()
    finally:
        conn.close()

    # Пишем CSV в память (StringIO -> encode)
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow(["id", "tg_user_id", "tg_username", "q_name", "q_age",
                     "q_city", "q_stack", "q_consent", "created_at"])
    for r in rows:
        writer.writerow(r)
    return buf.getvalue().encode("utf-8")

def delete_user_data(tg_user_id: int) -> int:
    """Удаляем все ответы конкретного пользователя. Возвращаем количество удалённых строк."""
    conn = connect_db()
    try:
        cur = conn.execute("DELETE FROM respondents WHERE tg_user_id = ?;", (tg_user_id,))
        conn.commit()
        return cur.rowcount or 0
    finally:
        conn.close()

# ------------------------- ХЕЛПЕРЫ ДЛЯ UI -------------------------
def menu_text() -> str:
    """Текст приветствия и инструкции в меню."""
    return (
        "👋 Привет! Это мини-анкета с сохранением в SQLite.\n\n"
        "Выберите действие на клавиатуре ниже:\n"
        f"• {BTN_SURVEY} — пройти опрос (5 вопросов)\n"
        f"• {BTN_STATS} — посмотреть агрегированную статистику\n"
        f"• {BTN_LAST} — увидеть последние 10 ответов\n"
        f"• {BTN_EXPORT} — выгрузить все ответы в CSV\n"
        f"• {BTN_DELETE_ME} — удалить все мои ответы из базы\n"
        f"• {BTN_HELP} — краткая справка\n\n"
        "В любой момент можно ввести /cancel, чтобы вернуться в меню."
    )

def format_stats(stats: Dict[str, object]) -> str:
    """Готовим человекочитаемый текст статистики."""
    total = stats["total"]
    avg_age = stats["avg_age"]
    min_age = stats["min_age"]
    max_age = stats["max_age"]
    by_stack = stats["by_stack"]
    top_cities = stats["top_cities"]
    consent_rate = stats["consent_rate"]

    # Блок возраста
    age_block = "нет данных"
    if avg_age is not None:
        age_block = f"средний {avg_age:.1f}, мин {min_age}, макс {max_age}"

    # Блок согласия
    consent_block = "нет данных"
    if consent_rate is not None:
        consent_block = f"{consent_rate*100:.1f}% согласий"

    # Блок по опыту
    if by_stack:
        stack_lines = [f"- {k}: {v}" for k, v in by_stack.items()]
        stack_block = "\n".join(stack_lines)
    else:
        stack_block = "нет данных"

    # ТОП-городов
    if top_cities:
        city_lines = [f"- {c}: {n}" for c, n in top_cities]
        cities_block = "\n".join(city_lines)
    else:
        cities_block = "нет данных"

    return (
        "📊 *Сводная статистика*\n"
        f"Всего ответов: *{total}*\n"
        f"Возраст: {age_block}\n"
        f"Согласие на обработку: {consent_block}\n\n"
        "*Опыт программирования:*\n"
        f"{stack_block}\n\n"
        "*ТОП-5 городов:*\n"
        f"{cities_block}"
    )

def format_last_rows(rows: List[Tuple]) -> str:
    """Форматируем последние записи (кратко в несколько строк)."""
    if not rows:
        return "Записей пока нет."
    lines = []
    for (id_, username, name, age, city, stack, consent, created_at) in rows:
        uname = f"@{username}" if username else "—"
        agree = "Да" if consent == 1 else "Нет"
        lines.append(
            f"#{id_} {uname}\n"
            f"  Имя: {name}; Возраст: {age}; Город: {city}\n"
            f"  Опыт: {stack}; Согласие: {agree}; Время: {created_at}"
        )
    return "🗂 *Последние ответы*\n" + "\n\n".join(lines)

# ------------------------- КОМАНДЫ (ВНЕ ДИАЛОГА ИЛИ МЕНЮ) -------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показываем меню при /start (и ставим состояние MENU)."""
    await update.message.reply_text(menu_text(), reply_markup=MENU_KEYBOARD, parse_mode="Markdown")
    return MENU

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/help — тоже в меню."""
    await update.message.reply_text(menu_text(), reply_markup=MENU_KEYBOARD, parse_mode="Markdown")
    return MENU

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cancel — всегда возвращает в меню и сбрасывает клавиатуру анкеты, если была."""
    await update.message.reply_text("Вы вернулись в главное меню.", reply_markup=MENU_KEYBOARD)
    return MENU

# ------------------------- ОБРАБОТКА МЕНЮ -------------------------
async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Находимся в состоянии MENU. По тексту кнопки решаем, что делать:
    - запустить анкету,
    - показать статистику,
    - показать последние,
    - экспорт CSV,
    - удалить мои данные,
    - показать справку.
    """
    text = (update.message.text or "").strip()

    if text == BTN_SURVEY:
        # Стартуем анкету: первый вопрос про имя, убираем меню-клавиатуру
        await update.message.reply_text(
            "Начинаем опрос. Отправьте /cancel, чтобы вернуться в меню.\n\n"
            "Вопрос 1/5: Как вас зовут?",
            reply_markup=ReplyKeyboardRemove(),
        )
        return Q_NAME

    elif text == BTN_STATS:
        stats = get_stats()
        await update.message.reply_text(format_stats(stats), parse_mode="Markdown", reply_markup=MENU_KEYBOARD)
        return MENU

    elif text == BTN_LAST:
        rows = get_last_rows(limit=10)
        await update.message.reply_text(format_last_rows(rows), parse_mode="Markdown", reply_markup=MENU_KEYBOARD)
        return MENU

    elif text == BTN_EXPORT:
        data = export_csv_bytes()
        # Отправляем файл как документ с читаемым именем
        await update.message.reply_document(
            document=InputFile(io.BytesIO(data), filename="survey_export.csv"),
            caption="Экспорт всех ответов в CSV.",
            reply_markup=MENU_KEYBOARD,
        )
        return MENU

    elif text == BTN_DELETE_ME:
        # Удаляем все записи этого пользователя
        deleted = delete_user_data(update.effective_user.id)
        await update.message.reply_text(
            f"Готово. Удалено ваших записей: {deleted}.",
            reply_markup=MENU_KEYBOARD,
        )
        return MENU

    elif text == BTN_HELP:
        await update.message.reply_text(menu_text(), reply_markup=MENU_KEYBOARD, parse_mode="Markdown")
        return MENU

    else:
        # Любой другой текст — напоминаем про меню
        await update.message.reply_text("Не понял команду. Выберите действие на клавиатуре ниже.", reply_markup=MENU_KEYBOARD)
        return MENU

# ------------------------- ЛОГИКА АНКЕТЫ (5 ВОПРОСОВ) -------------------------
async def q_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вопрос 1/5 — имя (произвольный текст, >=2 символов)."""
    name = (update.message.text or "").strip()
    if len(name) < 2:
        await update.message.reply_text("Имя слишком короткое. Попробуйте ещё раз:")
        return Q_NAME

    context.user_data["q_name"] = name
    await update.message.reply_text("Вопрос 2/5: Укажите ваш возраст (целым числом, например 27):")
    return Q_AGE

async def q_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вопрос 2/5 — возраст (целое 10..120)."""
    raw = (update.message.text or "").strip()
    if not raw.isdigit():
        await update.message.reply_text("Нужно целое число. Укажите возраст ещё раз:")
        return Q_AGE

    age = int(raw)
    if age < 10 or age > 120:
        await update.message.reply_text("Возраст вне диапазона (10–120). Ещё раз:")
        return Q_AGE

    context.user_data["q_age"] = age
    await update.message.reply_text("Вопрос 3/5: Из какого вы города?")
    return Q_CITY

async def q_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вопрос 3/5 — город (строка, >=2 символов)."""
    city = (update.message.text or "").strip()
    if len(city) < 2:
        await update.message.reply_text("Название города слишком короткое. Повторите:")
        return Q_CITY

    context.user_data["q_city"] = city
    # Готовим клавиатуру с вариантами опыта
    keyboard = [[KeyboardButton(opt)] for opt in STACK_OPTIONS]
    await update.message.reply_text(
        "Вопрос 4/5: Ваш опыт программирования?",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
    )
    return Q_STACK

async def q_stack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вопрос 4/5 — опыт (выбор из списка)."""
    stack = (update.message.text or "").strip()
    if stack not in STACK_OPTIONS:
        await update.message.reply_text("Пожалуйста, выберите один из вариантов на клавиатуре.")
        return Q_STACK

    context.user_data["q_stack"] = stack
    keyboard = [[KeyboardButton(opt)] for opt in CONSENT_OPTIONS]
    await update.message.reply_text(
        "Вопрос 5/5: Согласны на обработку и хранение ваших ответов? (Да/Нет)",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
    )
    return Q_CONSENT

async def q_consent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вопрос 5/5 — согласие (Да/Нет). После ответа — запись в БД и возврат в меню."""
    consent_text = (update.message.text or "").strip()
    if consent_text not in CONSENT_OPTIONS:
        await update.message.reply_text("Выберите «Да» или «Нет» на клавиатуре.")
        return Q_CONSENT

    consent = (consent_text == "Да")
    context.user_data["q_consent"] = consent

    # Пишем в БД
    try:
        insert_row(
            tg_user_id=update.effective_user.id,
            tg_username=update.effective_user.username,
            q_name=context.user_data["q_name"],
            q_age=context.user_data["q_age"],
            q_city=context.user_data["q_city"],
            q_stack=context.user_data["q_stack"],
            q_consent=consent,
        )
    except Exception as e:
        logger.exception("DB insert error")
        await update.message.reply_text(
            f"Не удалось сохранить ответы в базу данных: {e}",
            reply_markup=MENU_KEYBOARD,
        )
        return MENU

    await update.message.reply_text(
        "Спасибо! Ваши ответы записаны. Возвращаемся в меню.",
        reply_markup=MENU_KEYBOARD,
    )
    # После завершения анкеты возвращаемся в MENU
    return MENU

async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Глобальная ловушка исключений — пишем в логи, но пользователю много не рассказываем."""
    logger.exception("Unhandled error: %s", context.error)

# ------------------------- ТОЧКА ВХОДА -------------------------
def main():
    # 1) Загружаем .env, берём токен
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Не задан TELEGRAM_BOT_TOKEN. Укажите его в .env или переменных окружения.")

    # 2) Инициализируем БД (создаём таблицу при первом запуске)
    init_db()

    # 3) Строим приложение PTB
    app = Application.builder().token(token).build()

    # 4) ConversationHandler: одно состояние MENU + 5 шагов анкеты
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            CommandHandler("help", cmd_help),
        ],
        states={
            MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu)],
            Q_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, q_name)],
            Q_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, q_age)],
            Q_CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, q_city)],
            Q_STACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, q_stack)],
            Q_CONSENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, q_consent)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        name="survey_conversation",
        persistent=False,
    )

    # 5) Регистрируем обработчики и стартуем
    app.add_handler(conv)
    app.add_error_handler(on_error)

    logger.info("Bot is starting...")
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
