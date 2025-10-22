# -*- coding: utf-8 -*-
"""
Бот-справочник с многоуровневым меню на ReplyKeyboardMarkup.

Возможности:
- Красивое главное меню (кнопки с эмодзи).
- Переходы по разделам и подпунктам через кнопки.
- Кнопки "Назад" и "В меню".
- /start и /help показывают главное меню.
- Тексты разделов — заглушки Lorem Ipsum (можете заменить на свои).

Зависимости:
    python-telegram-bot==21.4
    python-dotenv==1.0.1

Запуск:
    1) pip install -r requirements.txt (или команды из README выше)
    2) .env с TELEGRAM_BOT_TOKEN=...
    3) python bot_reference.py
"""

import os
import logging
from typing import Dict, Any, Optional, List

from dotenv import load_dotenv
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
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
logger = logging.getLogger("reference-bot")

# ------------------------- СОСТОЯНИЯ (FSM) -------------------------
MAIN, ABOUT, PRODUCTS, PRICING, FAQ, CONTACTS = range(6)

# ------------------------- ТЕКСТЫ-ЗАГЛУШКИ -------------------------
LOREM = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit. "
    "Suspendisse potenti. Quisque vestibulum, nunc non placerat "
    "hendrerit, nibh quam accumsan neque, in fermentum erat erat at "
    "nisi. Integer posuere bibendum lorem, at porttitor leo posuere eu."
)

ABOUT_TEXT = (
    "🔷 О компании\n\n"
    f"{LOREM}\n\n"
    "Наша миссия — делать информацию доступной. "
    "В этом разделе вы можете разместить краткую справку о вашей организации."
)

PRICING_TEXT = (
    "💸 Тарифы и цены\n\n"
    f"{LOREM}\n\n"
    "— Базовый: 0 ₽/мес (демо)\n"
    "— Стандарт: 990 ₽/мес\n"
    "— Премиум: 2990 ₽/мес\n\n"
    "Цены — примеры. Замените на реальные."
)

FAQ_TEXT = (
    "❓ Частые вопросы\n\n"
    "Q: Как начать?\n"
    f"A: {LOREM}\n\n"
    "Q: Как отменить подписку?\n"
    f"A: {LOREM}\n\n"
    "Q: Где документация?\n"
    f"A: {LOREM}\n"
)

CONTACTS_TEXT = (
    "📞 Контакты\n\n"
    f"{LOREM}\n\n"
    "Email: help@example.com\n"
    "Телефон: +7 (999) 000-00-00\n"
    "Адрес: 123456, Россия, Пример-город, ул. Образцовая, 1"
)

# Подразделы «Продукты»
PRODUCT_A_TEXT = (
    "🧩 Продукт А — кратко\n\n"
    f"{LOREM}\n\n"
    "Основные преимущества:\n"
    "• Быстрый старт\n• Простая настройка\n• Масштабируемость"
)
PRODUCT_B_TEXT = (
    "🧩 Продукт Б — кратко\n\n"
    f"{LOREM}\n\n"
    "Особенности:\n"
    "• Расширяемые модули\n• Интеграции\n• Поддержка 24/7"
)
PRODUCT_C_TEXT = (
    "🧩 Продукт В — кратко\n\n"
    f"{LOREM}\n\n"
    "Подходит для:\n"
    "• Небольших команд\n• Пилотов\n• Обучения"
)

# ------------------------- КНОПКИ МЕНЮ -------------------------
BTN_BACK = "⬅️ Назад"
BTN_HOME = "🏠 В меню"

# Главное меню
BTN_ABOUT = "ℹ️ О компании"
BTN_PRODUCTS = "🧩 Продукты"
BTN_PRICING = "💸 Цены"
BTN_FAQ = "❓ FAQ"
BTN_CONTACTS = "📞 Контакты"
BTN_HELP = "❔ Справка"

# Подменю «Продукты»
BTN_PROD_A = "🧩 Продукт А"
BTN_PROD_B = "🧩 Продукт Б"
BTN_PROD_C = "🧩 Продукт В"

# ------------------------- ПОМОЩНИКИ ДЛЯ КЛАВИАТУР -------------------------
def main_keyboard() -> ReplyKeyboardMarkup:
    """Главное меню."""
    rows = [
        [KeyboardButton(BTN_ABOUT), KeyboardButton(BTN_PRODUCTS)],
        [KeyboardButton(BTN_PRICING), KeyboardButton(BTN_FAQ)],
        [KeyboardButton(BTN_CONTACTS), KeyboardButton(BTN_HELP)],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def section_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура секций: Назад/Домой."""
    rows = [
        [KeyboardButton(BTN_BACK), KeyboardButton(BTN_HOME)],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def products_keyboard() -> ReplyKeyboardMarkup:
    """Подменю продуктов + Навигация."""
    rows = [
        [KeyboardButton(BTN_PROD_A), KeyboardButton(BTN_PROD_B)],
        [KeyboardButton(BTN_PROD_C)],
        [KeyboardButton(BTN_BACK), KeyboardButton(BTN_HOME)],
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

# ------------------------- ТЕКСТ МЕНЮ -------------------------
def menu_text() -> str:
    """Текст приветствия в главном меню."""
    return (
        "👋 Добро пожаловать в бот-справочник!\n\n"
        "Выберите раздел на клавиатуре ниже:\n"
        f"• {BTN_ABOUT}\n"
        f"• {BTN_PRODUCTS}\n"
        f"• {BTN_PRICING}\n"
        f"• {BTN_FAQ}\n"
        f"• {BTN_CONTACTS}\n"
        f"• {BTN_HELP}\n\n"
        "В любой момент используйте кнопки «Назад» или «В меню»."
    )

# ------------------------- ОБРАБОТЧИКИ КОМАНД -------------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Старт: показываем главное меню и ставим состояние MAIN."""
    await update.message.reply_text(menu_text(), reply_markup=main_keyboard())
    return MAIN

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Справка: по сути, тоже главное меню + подсказка."""
    await update.message.reply_text(
        "Это бот-справочник. Навигируйте по разделам через кнопки.\n"
        "Команды: /start, /help, /cancel.",
        reply_markup=main_keyboard(),
    )
    return MAIN

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена: возвращаемся в главное меню, убираем возможные вложенные клавиатуры."""
    await update.message.reply_text("Вы в главном меню.", reply_markup=main_keyboard())
    return MAIN

# ------------------------- ОБРАБОТКА ГЛАВНОГО МЕНЮ -------------------------
async def handle_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Находимся в MAIN: реагируем на нажатия главных кнопок."""
    text = (update.message.text or "").strip()

    if text == BTN_ABOUT:
        await update.message.reply_text(ABOUT_TEXT, reply_markup=section_keyboard())
        return ABOUT

    if text == BTN_PRODUCTS:
        await update.message.reply_text("Раздел «Продукты». Выберите подпункт:", reply_markup=products_keyboard())
        return PRODUCTS

    if text == BTN_PRICING:
        await update.message.reply_text(PRICING_TEXT, reply_markup=section_keyboard())
        return PRICING

    if text == BTN_FAQ:
        await update.message.reply_text(FAQ_TEXT, reply_markup=section_keyboard())
        return FAQ

    if text == BTN_CONTACTS:
        await update.message.reply_text(CONTACTS_TEXT, reply_markup=section_keyboard())
        return CONTACTS

    if text == BTN_HELP:
        return await cmd_help(update, context)

    # Любой другой текст — подскажем про меню
    await update.message.reply_text("Пожалуйста, используйте кнопки ниже.", reply_markup=main_keyboard())
    return MAIN

# ------------------------- ОБРАБОТЧИКИ СЕКЦИЙ -------------------------
async def handle_about(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Секция «О компании»: обрабатываем навигацию."""
    text = (update.message.text or "").strip()
    if text == BTN_BACK:
        await update.message.reply_text("Вы вернулись в главное меню.", reply_markup=main_keyboard())
        return MAIN
    if text == BTN_HOME:
        await update.message.reply_text("Главное меню:", reply_markup=main_keyboard())
        return MAIN

    # Повторно показать раздел при любом другом вводе
    await update.message.reply_text(ABOUT_TEXT, reply_markup=section_keyboard())
    return ABOUT

async def handle_products(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Секция «Продукты»: подпункты + навигация."""
    text = (update.message.text or "").strip()

    if text == BTN_PROD_A:
        await update.message.reply_text(PRODUCT_A_TEXT, reply_markup=products_keyboard())
        return PRODUCTS

    if text == BTN_PROD_B:
        await update.message.reply_text(PRODUCT_B_TEXT, reply_markup=products_keyboard())
        return PRODUCTS

    if text == BTN_PROD_C:
        await update.message.reply_text(PRODUCT_C_TEXT, reply_markup=products_keyboard())
        return PRODUCTS

    if text == BTN_BACK:
        await update.message.reply_text("Вы вернулись в главное меню.", reply_markup=main_keyboard())
        return MAIN

    if text == BTN_HOME:
        await update.message.reply_text("Главное меню:", reply_markup=main_keyboard())
        return MAIN

    # На любой иной ввод — повторно показываем подменю продуктов
    await update.message.reply_text("Раздел «Продукты». Выберите подпункт:", reply_markup=products_keyboard())
    return PRODUCTS

async def handle_pricing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Секция «Цены»: навигация."""
    text = (update.message.text or "").strip()
    if text == BTN_BACK:
        await update.message.reply_text("Вы вернулись в главное меню.", reply_markup=main_keyboard())
        return MAIN
    if text == BTN_HOME:
        await update.message.reply_text("Главное меню:", reply_markup=main_keyboard())
        return MAIN

    await update.message.reply_text(PRICING_TEXT, reply_markup=section_keyboard())
    return PRICING

async def handle_faq(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Секция «FAQ»: навигация."""
    text = (update.message.text or "").strip()
    if text == BTN_BACK:
        await update.message.reply_text("Вы вернулись в главное меню.", reply_markup=main_keyboard())
        return MAIN
    if text == BTN_HOME:
        await update.message.reply_text("Главное меню:", reply_markup=main_keyboard())
        return MAIN

    await update.message.reply_text(FAQ_TEXT, reply_markup=section_keyboard())
    return FAQ

async def handle_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Секция «Контакты»: навигация."""
    text = (update.message.text or "").strip()
    if text == BTN_BACK:
        await update.message.reply_text("Вы вернулись в главное меню.", reply_markup=main_keyboard())
        return MAIN
    if text == BTN_HOME:
        await update.message.reply_text("Главное меню:", reply_markup=main_keyboard())
        return MAIN

    await update.message.reply_text(CONTACTS_TEXT, reply_markup=section_keyboard())
    return CONTACTS

# ------------------------- ГЛОБАЛЬНАЯ ОШИБКА -------------------------
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ловим необработанные исключения, пишем в логи, пользователю — мягко."""
    logger.exception("Unhandled error: %s", context.error)
    try:
        if isinstance(update, Update) and update.effective_message:
            await update.effective_message.reply_text(
                "Упс! Что-то пошло не так. Попробуйте ещё раз командой /start.",
                reply_markup=main_keyboard(),
            )
    except Exception:  # безопасный бэкап
        pass

# ------------------------- ТОЧКА ВХОДА -------------------------
def main() -> None:
    """Создание и запуск приложения PTB."""
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Не задан TELEGRAM_BOT_TOKEN. Укажите его в .env или переменных окружения.")

    app = Application.builder().token(token).build()

    # Один ConversationHandler с состояниями MAIN/ABOUT/PRODUCTS/PRICING/FAQ/CONTACTS
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start), CommandHandler("help", cmd_help)],
        states={
            MAIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_main)],
            ABOUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_about)],
            PRODUCTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_products)],
            PRICING: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_pricing)],
            FAQ: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_faq)],
            CONTACTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_contacts)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        name="reference_conversation",
        persistent=False,
    )

    app.add_handler(conv)
    app.add_error_handler(on_error)

    logger.info("Reference bot is starting...")
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
