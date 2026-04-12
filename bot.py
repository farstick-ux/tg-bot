import os
import re
import subprocess
import sys
import time
import asyncio
import logging
import sqlite3
import json
from datetime import datetime
from collections import defaultdict
from typing import Dict, List, Optional, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler, 
    filters, ContextTypes
)
import requests
import aiohttp
from bs4 import BeautifulSoup

# ========== НАСТРОЙКИ ==========
TOKEN = os.getenv("BOT_TOKEN", "7632894734:AAGAyaDvdpPgzDgq244Gzj5U4ASms_VQGV0")
ADMIN_IDS = [123456789]  # Замените на ваш Telegram ID

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
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

def save_search(user_id: int, search_type: str, query: str, result: str):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("INSERT INTO searches VALUES (?, ?, ?, ?, ?)",
              (user_id, search_type, query, result[:500], datetime.now().isoformat()))
    conn.commit()
    conn.close()

# ========== RATE LIMITING ==========
user_commands = defaultdict(list)

def rate_limit(user_id: int, limit: int = 10, per_seconds: int = 60) -> Tuple[bool, int]:
    """Проверка лимита команд. Возвращает (разрешено, осталось_секунд)"""
    now = time.time()
    user_commands[user_id] = [t for t in user_commands[user_id] if now - t < per_seconds]
    
    if len(user_commands[user_id]) >= limit:
        oldest = min(user_commands[user_id])
        wait_time = int(per_seconds - (now - oldest))
        return False, wait_time
    
    user_commands[user_id].append(now)
    return True, 0

# ========== АВТОМАТИЧЕСКОЕ ОБНОВЛЕНИЕ ==========
async def check_for_updates():
    """Проверка обновлений на GitHub (каждый час)"""
    while True:
        await asyncio.sleep(3600)  # 1 час
        try:
            # Проверяем последний коммит на GitHub
            repo_url = "https://api.github.com/repos/YOUR_USERNAME/YOUR_REPO/commits/main"
            async with aiohttp.ClientSession() as session:
                async with session.get(repo_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        latest_commit = data['sha'][:7]
                        
                        # Сравниваем с текущей версией
                        current_version = os.getenv('BOT_VERSION', 'unknown')
                        if latest_commit != current_version:
                            logger.info(f"Доступно обновление! {current_version} -> {latest_commit}")
                            # Отправляем админу
                            for admin_id in ADMIN_IDS:
                                await send_message(admin_id, f"🔄 Доступно обновление бота!\nНовая версия: {latest_commit}")
        except Exception as e:
            logger.error(f"Ошибка проверки обновлений: {e}")

async def auto_restart():
    """Автоматический перезапуск каждый день в 4 утра"""
    while True:
        now = datetime.now()
        next_restart = now.replace(hour=4, minute=0, second=0, microsecond=0)
        if now >= next_restart:
            next_restart += timedelta(days=1)
        
        wait_seconds = (next_restart - now).total_seconds()
        await asyncio.sleep(wait_seconds)
        
        logger.info("Автоматический перезапуск...")
        os.execv(sys.executable, ['python'] + sys.argv)

# ========== ФУНКЦИИ ПОИСКА ==========

async def run_email_search(email: str) -> str:
    """Поиск по email через holehe"""
    try:
        result = await asyncio.to_thread(
            subprocess.run, 
            ["holehe", email, "--no-color"], 
            capture_output=True, 
            text=True, 
            timeout=60
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
    """Поиск по никнейму"""
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
    """Поиск по IP"""
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
🗺️ Координаты: {data.get('lat')}, {data.get('lon')}
💻 Организация: {data.get('org', 'Неизвестно')}"""
                return f"❌ Не удалось найти IP {ip}"
    except Exception as e:
        return f"❌ Ошибка: {e}"

async def run_phone_search(phone: str) -> str:
    """Поиск по телефону"""
    phone_clean = re.sub(r'[^0-9+]', '', phone)
    result = f"📱 ТЕЛЕФОН: {phone_clean}\n\n"
    result += f"• WhatsApp: https://wa.me/{phone_clean}\n"
    result += f"• Telegram: https://t.me/{phone_clean}\n"
    result += f"• Google: https://www.google.com/search?q={phone_clean}\n"
    return result

async def run_car_search(plate_number: str) -> str:
    """Поиск по номеру автомобиля"""
    plate_clean = re.sub(r'[^A-Za-z0-9]', '', plate_number).upper()
    
    result = f"🚗 НОМЕР АВТО: {plate_clean}\n\n"
    
    # 1. Проверка через ГИБДД (Россия)
    if re.match(r'^[A-Z]{1}\d{3}[A-Z]{2}\d{2,3}$', plate_clean):
        result += "🇷🇺 РОССИЯ:\n"
        result += f"• ГИБДД: https://xn--90adear.xn--p1ai/check/auto/{plate_clean}\n"
        result += f"• Автокод: https://avtokod.mos.ru/CheckCar/Index?number={plate_clean}\n"
        result += f"• Штрафы ГИБДД: https://xn--90adear.xn--p1ai/check/fines/{plate_clean}\n"
    
    # 2. Украина
    elif re.match(r'^[A-Z]{2}\d{4}[A-Z]{2}$', plate_clean):
        result += "🇺🇦 УКРАИНА:\n"
        result += f"• Опендатабот: https://opendatabot.ua/c/auto/{plate_clean}\n"
        result += f"• Auto.ria: https://auto.ria.ua/search/?number={plate_clean}\n"
    
    # 3. Казахстан
    elif re.match(r'^[A-Z]{1}\d{3}[A-Z]{3}$', plate_clean):
        result += "🇰🇿 КАЗАХСТАН:\n"
        result += f"• E-Gov: https://egov.kz/cms/ru/services/transport/check_vehicle_auto/{plate_clean}\n"
    
    # 4. Беларусь
    elif re.match(r'^\d{4}[A-Z]{2}-\d$', plate_clean):
        result += "🇧🇾 БЕЛАРУСЬ:\n"
        result += f"• МВД РБ: https://web.mvd.gov.by/ru/check-auto/{plate_clean}\n"
    
    else:
        result += "🌍 МЕЖДУНАРОДНЫЙ ПОИСК:\n"
    
    # Общие сервисы
    result += f"\n🔍 ДОПОЛНИТЕЛЬНО:\n"
    result += f"• Google: https://www.google.com/search?q={plate_clean}+номер+авто\n"
    result += f"• Avito: https://www.avito.ru/all?q={plate_clean}\n"
    result += f"• Дром: https://www.drom.ru/search/?text={plate_clean}\n"
    
    # Carfax для иностранных номеров
    if len(plate_clean) > 4:
        result += f"• Carfax (только платно): https://www.carfax.com/vehicle/{plate_clean}\n"
    
    return result

async def run_photo_search() -> str:
    """Поиск по фото"""
    return """🔎 ПОИСК ПО ФОТО

🔗 СЕРВИСЫ ДЛЯ ПОИСКА:

1. Google Images:
   https://images.google.com

2. Yandex Images:
   https://yandex.com/images/

3. TinEye:
   https://tineye.com

4. Bing Visual Search:
   https://www.bing.com/visualsearch

5. Reversely.ai (поиск лиц):
   https://www.reversely.ai/ru/face-search

6. PimEyes (поиск лиц):
   https://pimeyes.com

📌 Инструкция:
1. Откройте любой сервис
2. Нажмите на иконку камеры
3. Загрузите фото
4. Получите результаты

💡 Совет: Используйте несколько сервисов для лучших результатов"""

# ========== ИНЛАЙН-КЛАВИАТУРЫ ==========
def get_main_keyboard() -> InlineKeyboardMarkup:
    """Главное меню"""
    keyboard = [
        [InlineKeyboardButton("🔍 Поиск по email", callback_data="search_email")],
        [InlineKeyboardButton("👤 Поиск по никнейму", callback_data="search_nickname")],
        [InlineKeyboardButton("🌐 Поиск по IP", callback_data="search_ip")],
        [InlineKeyboardButton("📱 Поиск по телефону", callback_data="search_phone")],
        [InlineKeyboardButton("🚗 Поиск по номеру авто", callback_data="search_car")],
        [InlineKeyboardButton("🖼️ Поиск по фото", callback_data="search_photo")],
        [InlineKeyboardButton("❓ Помощь", callback_data="help")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_keyboard() -> InlineKeyboardMarkup:
    """Кнопка возврата в меню"""
    keyboard = [[InlineKeyboardButton("🔙 Назад в меню", callback_data="menu")]]
    return InlineKeyboardMarkup(keyboard)

# ========== ОБРАБОТЧИКИ КОМАНД ==========

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    user_id = user.id
    
    # Rate limiting
    allowed, wait_time = rate_limit(user_id)
    if not allowed:
        await update.message.reply_text(f"⏳ Слишком много запросов! Подождите {wait_time} секунд.")
        return
    
    # Регистрация пользователя
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users VALUES (?, ?, ?)",
              (user_id, datetime.now().isoformat(), datetime.now().isoformat()))
    c.execute("UPDATE users SET last_active = ? WHERE user_id = ?",
              (datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()
    
    welcome_text = f"""🤖 Привет, {user.first_name}!

Я OSINT бот для поиска информации.

🔍 Что я умею:
• Поиск по email (holehe)
• Поиск по никнейму
• Поиск по IP адресу
• Поиск по номеру телефона
• Поиск по номеру авто
• Поиск по фото (ссылки)

Используй кнопки ниже для навигации 👇"""

    await update.message.reply_text(welcome_text, reply_markup=get_main_keyboard())

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🔍 Главное меню:", reply_markup=get_main_keyboard())

async def search_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос данных для поиска"""
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
        prompts.get(search_type, "Введите данные для поиска:"),
        reply_markup=get_back_keyboard()
    )

async def handle_search_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка введенных данных для поиска"""
    user_id = update.effective_user.id
    search_type = context.user_data.get('search_type')
    query_text = update.message.text.strip()
    
    # Rate limiting
    allowed, wait_time = rate_limit(user_id)
    if not allowed:
        await update.message.reply_text(f"⏳ Подождите {wait_time} секунд перед следующим запросом.")
        return
    
    # Отправляем сообщение о начале поиска
    status_msg = await update.message.reply_text(f"🔍 Поиск... Это может занять до 30 секунд.")
    
    # Выполняем поиск
    result = ""
    if search_type == "email":
        if "@" not in query_text:
            await update.message.reply_text("❌ Неверный формат email!", reply_markup=get_back_keyboard())
            return
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
    
    # Сохраняем в БД
    save_search(user_id, search_type, query_text, result)
    
    # Удаляем сообщение о статусе
    await status_msg.delete()
    
    # Отправляем результат
    await update.message.reply_text(result, reply_markup=get_back_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Помощь"""
    help_text = """📚 *ПОМОЩЬ ПО БОТУ*

*Команды:*
/start - Запустить бота
/menu - Главное меню
/help - Эта справка
/stats - Моя статистика

*Как пользоваться:*
1. Используй кнопки в меню
2. Введи данные для поиска
3. Жди результат

*Ограничения:*
• 10 запросов в минуту
• Максимум 30 секунд на поиск

*Вопросы:* @support_username"""
    
    await update.message.reply_text(help_text, parse_mode='Markdown', reply_markup=get_back_keyboard())

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика пользователя"""
    user_id = update.effective_user.id
    
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    # Количество поисков
    c.execute("SELECT COUNT(*) FROM searches WHERE user_id = ?", (user_id,))
    total_searches = c.fetchone()[0]
    
    # По типам
    c.execute("SELECT type, COUNT(*) FROM searches WHERE user_id = ? GROUP BY type", (user_id,))
    type_stats = c.fetchall()
    
    # Последний поиск
    c.execute("SELECT date FROM searches WHERE user_id = ? ORDER BY date DESC LIMIT 1", (user_id,))
    last_search = c.fetchone()
    
    conn.close()
    
    stats_text = f"""📊 *ВАША СТАТИСТИКА*

Всего поисков: {total_searches}
Последний поиск: {last_search[0][:19] if last_search else 'Нет'}

*По типам:*"""
    
    for search_type, count in type_stats:
        emoji = {"email": "📧", "nickname": "👤", "ip": "🌐", "phone": "📱", "car": "🚗"}.get(search_type, "🔍")
        stats_text += f"\n{emoji} {search_type}: {count}"
    
    await update.message.reply_text(stats_text, parse_mode='Markdown', reply_markup=get_back_keyboard())

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ошибок"""
    logger.error(f"Ошибка: {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text("❌ Произошла ошибка. Попробуйте позже.")

# ========== ЗАПУСК БОТА ==========
async def main():
    """Запуск бота"""
    # Создаем приложение
    application = Application.builder().token(TOKEN).build()
    
    # Регистрируем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("menu", menu_callback))
    
    # Регистрируем callback обработчики
    application.add_handler(CallbackQueryHandler(search_prompt, pattern="^search_"))
    application.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu$"))
    application.add_handler(CallbackQueryHandler(help_command, pattern="^help$"))
    application.add_handler(CallbackQueryHandler(stats_command, pattern="^stats$"))
    
    # Обработчик текстовых сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_search_input))
    
    # Обработчик ошибок
    application.add_error_handler(error_handler)
    
    # Запускаем фоновые задачи
    asyncio.create_task(check_for_updates())
    asyncio.create_task(auto_restart())
    
    # Запускаем бота
    logger.info("Бот запущен!")
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
