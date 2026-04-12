import os
import re
import subprocess
import time
import asyncio
import logging
import sqlite3
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Optional, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    filters, ContextTypes
)
import aiohttp

# ========== НАСТРОЙКИ ==========
TOKEN = os.getenv("BOT_TOKEN", "7632894734:AAGAyaDvdpPgzDgq244Gzj5U4ASms_VQGV0")
ADMIN_IDS = []  # Добавьте сюда свой ID после получения от @userinfobot

# Логирование
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ========== БАЗА ДАННЫХ ==========
def init_db():
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS searches
                 (user_id INT, type TEXT, query TEXT, result TEXT, date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INT PRIMARY KEY, first_seen TEXT, last_active TEXT)''')
    conn.commit()
    conn.close()

init_db()

# ========== RATE LIMITING ==========
user_commands = defaultdict(list)

def rate_limit(user_id: int, limit: int = 10, per_seconds: int = 60) -> Tuple[bool, int]:
    now = time.time()
    user_commands[user_id] = [t for t in user_commands[user_id] if now - t < per_seconds]
    if len(user_commands[user_id]) >= limit:
        oldest = min(user_commands[user_id])
        wait_time = int(per_seconds - (now - oldest))
        return False, wait_time
    user_commands[user_id].append(now)
    return True, 0

# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard():
    keyboard = [
        [InlineKeyboardButton("🔍 Поиск по email", callback_data="search_email")],
        [InlineKeyboardButton("👤 Поиск по никнейму", callback_data="search_nickname")],
        [InlineKeyboardButton("🌐 Поиск по IP", callback_data="search_ip")],
        [InlineKeyboardButton("📱 Поиск по телефону", callback_data="search_phone")],
        [InlineKeyboardButton("🚗 Поиск по номеру авто", callback_data="search_car")],
        [InlineKeyboardButton("🖼️ Поиск по фото", callback_data="search_photo")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_keyboard():
    keyboard = [[InlineKeyboardButton("🔙 Назад в меню", callback_data="menu")]]
    return InlineKeyboardMarkup(keyboard)

# ========== ФУНКЦИИ ПОИСКА ==========
async def run_email_search(email: str) -> str:
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            ["holehe", email, "--no-color"],
            capture_output=True, text=True, timeout=60
        )
        clean = re.sub(r'\x1b\[[0-9;]*m', '', result.stdout)
        found_sites = []
        for line in clean.split("\n"):
            if "[+]" in line:
                site = line.replace("[+]", "").strip()
                site = re.sub(r'https?://', '', site)
                site = site.split()[0] if site.split() else site
                if len(site) > 3 and site.lower() not in ['email', 'mail']:
                    found_sites.append(f"✅ {site[:50]}")
        if found_sites:
            return f"🔍 Email: {email}\n\n✅ НАЙДЕНО:\n" + "\n".join(found_sites[:20])
        return f"🔍 Email: {email}\n\n❌ Ничего не найдено"
    except Exception as e:
        return f"❌ Ошибка: {e}"

async def run_nickname_search(username: str) -> str:
    sites = {
        "TikTok": f"https://www.tiktok.com/@{username}",
        "Instagram": f"https://instagram.com/{username}",
        "Twitter": f"https://twitter.com/{username}",
        "Telegram": f"https://t.me/{username}",
        "GitHub": f"https://github.com/{username}",
        "YouTube": f"https://youtube.com/@{username}",
        "Twitch": f"https://twitch.tv/{username}",
        "Reddit": f"https://reddit.com/user/{username}",
    }
    found = []
    async with aiohttp.ClientSession() as session:
        for site_name, url in sites.items():
            try:
                async with session.get(url, timeout=5, allow_redirects=False) as resp:
                    if resp.status == 200:
                        if site_name == "Telegram":
                            text = await resp.text()
                            if "tgme_page_title" in text and "If you have Telegram" not in text:
                                found.append(f"✅ {site_name}: {url}")
                        else:
                            found.append(f"✅ {site_name}: {url}")
            except:
                pass
    if found:
        return f"🔍 НИКНЕЙМ: {username}\n\n" + "\n".join(found)
    return f"🔍 По никнейму {username} ничего не найдено"

async def run_ip_search(ip: str) -> str:
    ip_pattern = re.compile(r'^(\d{1,3}\.){3}\d{1,3}$')
    if not ip_pattern.match(ip):
        return "❌ Неверный формат IP-адреса"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://ip-api.com/json/{ip}", timeout=10) as resp:
                data = await resp.json()
                if data.get('status') == 'success':
                    return f"""🌐 IP: {ip}

📍 Страна: {data.get('country', 'Неизвестно')}
🏙️ Город: {data.get('city', 'Неизвестно')}
🏢 Провайдер: {data.get('isp', 'Неизвестно')}
🗺️ Координаты: {data.get('lat')}, {data.get('lon')}"""
                return f"❌ Не удалось найти IP {ip}"
    except Exception as e:
        return f"❌ Ошибка: {e}"

async def run_phone_search(phone: str) -> str:
    phone_clean = re.sub(r'[^0-9+]', '', phone)
    result = f"📱 ТЕЛЕФОН: {phone_clean}\n\n"
    result += f"• WhatsApp: https://wa.me/{phone_clean}\n"
    result += f"• Telegram: https://t.me/{phone_clean}\n"
    result += f"• Google: https://www.google.com/search?q={phone_clean}\n"
    return result

async def run_car_search(plate_number: str) -> str:
    plate_clean = re.sub(r'[^A-Za-z0-9]', '', plate_number).upper()
    result = f"🚗 НОМЕР АВТО: {plate_clean}\n\n"
    
    if re.match(r'^[A-Z]{1}\d{3}[A-Z]{2}\d{2,3}$', plate_clean):
        result += "🇷🇺 РОССИЯ:\n"
        result += f"• ГИБДД: https://xn--90adear.xn--p1ai/check/auto/{plate_clean}\n"
    elif re.match(r'^[A-Z]{2}\d{4}[A-Z]{2}$', plate_clean):
        result += "🇺🇦 УКРАИНА:\n"
        result += f"• Опендатабот: https://opendatabot.ua/c/auto/{plate_clean}\n"
    else:
        result += "🌍 МЕЖДУНАРОДНЫЙ ПОИСК:\n"
    
    result += f"\n🔍 Google: https://www.google.com/search?q={plate_clean}+номер+авто\n"
    return result

async def run_photo_search() -> str:
    return """🔎 ПОИСК ПО ФОТО

🔗 СЕРВИСЫ:
1. Google Images: https://images.google.com
2. Yandex Images: https://yandex.com/images/
3. TinEye: https://tineye.com
4. Reversely.ai: https://www.reversely.ai/ru/face-search

📌 Инструкция: Откройте сервис → Нажмите на иконку камеры → Загрузите фото"""

# ========== ОБРАБОТЧИКИ ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"🤖 Привет, {user.first_name}!\n\nЯ OSINT бот для поиска информации.\n\nИспользуй кнопки ниже 👇",
        reply_markup=get_main_keyboard()
    )

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🔍 Главное меню:", reply_markup=get_main_keyboard())

async def search_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    search_type = query.data.replace("search_", "")
    context.user_data['search_type'] = search_type
    
    prompts = {
        "email": "📧 Введите email для поиска:",
        "nickname": "👤 Введите никнейм для поиска:",
        "ip": "🌐 Введите IP адрес для поиска:",
        "phone": "📱 Введите номер телефона для поиска:",
        "car": "🚗 Введите номер автомобиля для поиска:",
        "photo": "🖼️ Поиск по фото"
    }
    
    await query.edit_message_text(
        prompts.get(search_type, "Введите данные:"),
        reply_markup=get_back_keyboard()
    )

async def handle_search_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    search_type = context.user_data.get('search_type')
    query_text = update.message.text.strip()
    
    allowed, wait_time = rate_limit(user_id)
    if not allowed:
        await update.message.reply_text(f"⏳ Подождите {wait_time} секунд.")
        return
    
    status_msg = await update.message.reply_text("🔍 Поиск...")
    
    if search_type == "email":
        result = await run_email_search(query_text)
    elif search_type == "nickname":
        result = await run_nickname_search(query_text)
    elif search_type == "ip":
        result = await run_ip_search(query_text)
    elif search_type == "phone":
        result = await run_phone_search(query_text)
    elif search_type == "car":
        result = await run_car_search(query_text)
    elif search_type == "photo":
        result = await run_photo_search()
    else:
        result = "❌ Неизвестный тип поиска"
    
    await status_msg.delete()
    await update.message.reply_text(result, reply_markup=get_back_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 *ПОМОЩЬ*\n\nКоманды:\n/start - Запустить\n/menu - Главное меню\n/help - Помощь\n\n10 запросов в минуту",
        parse_mode='Markdown',
        reply_markup=get_back_keyboard()
    )

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Главное меню:", reply_markup=get_main_keyboard())

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Ошибка: {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text("❌ Ошибка. Попробуйте позже.")

# ========== ЗАПУСК ==========
def main():
    """Запуск бота"""
    # Создаем приложение
    application = Application.builder().token(TOKEN).build()
    
    # Команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("menu", menu_command))
    
    # Callback обработчики для кнопок
    application.add_handler(CallbackQueryHandler(search_prompt, pattern="^search_"))
    application.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu$"))
    application.add_handler(CallbackQueryHandler(help_command, pattern="^help$"))
    
    # Обработка текста
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search_input))
    
    # Ошибки
    application.add_error_handler(error_handler)
    
    # Запуск
    print("🤖 Бот запущен! Нажми Ctrl+C для остановки.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
