import asyncio
import logging
import re
import subprocess
import time
import os
import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Токен и админы
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [6695578489]

if not TOKEN:
    print("❌ Ошибка: BOT_TOKEN не найден в переменных окружения!")
    exit(1)

bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()

# ========== БАЗА ДАННЫХ ==========
def init_db():
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS searches
                 (user_id INT, type TEXT, query TEXT, result TEXT, date TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INT PRIMARY KEY, first_seen TEXT, last_active TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS premium
                 (user_id INT PRIMARY KEY, until_date TEXT)''')
    conn.commit()
    conn.close()

init_db()

def save_search(user_id, search_type, query, result):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("INSERT INTO searches VALUES (?, ?, ?, ?, ?)",
              (user_id, search_type, query, result[:500], datetime.now().isoformat()))
    conn.commit()
    conn.close()

# ========== ПРЕМИУМ ФУНКЦИИ ==========
def is_premium(user_id):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT until_date FROM premium WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    if result:
        if result[0] == "forever":
            return True
        return datetime.now().isoformat() < result[0]
    return False

def add_premium(user_id, days=30, forever=False):
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    if forever:
        until = "forever"
    else:
        until = (datetime.now() + timedelta(days=days)).isoformat()
    c.execute("INSERT OR REPLACE INTO premium VALUES (?, ?)", (user_id, until))
    conn.commit()
    conn.close()

# ========== ПРОМОКОДЫ ==========
promocodes = {}

def save_promocodes():
    with open("promocodes.txt", "w") as f:
        for code, data in promocodes.items():
            f.write(f"{code}|{data['type']}|{data['uses']}|{data['used']}\n")

def load_promocodes():
    global promocodes
    if os.path.exists("promocodes.txt"):
        with open("promocodes.txt", "r") as f:
            for line in f:
                parts = line.strip().split("|")
                if len(parts) == 4:
                    code, promo_type, uses, used = parts
                    promocodes[code] = {"type": promo_type, "uses": int(uses), "used": int(used)}

def add_promocode(code, promo_type, uses):
    promocodes[code] = {"type": promo_type, "uses": uses, "used": 0}
    save_promocodes()

def remove_promocode(code):
    if code in promocodes:
        del promocodes[code]
        save_promocodes()

def use_promocode(code):
    if code not in promocodes:
        return None
    promo = promocodes[code]
    if promo["uses"] > 0 and promo["used"] >= promo["uses"]:
        return "expired"
    promo["used"] += 1
    save_promocodes()
    return promo["type"]

load_promocodes()

# ========== RATE LIMITING ==========
user_commands = defaultdict(list)
daily_requests = defaultdict(int)
last_reset = datetime.now().date()

def check_daily_limit(user_id):
    global last_reset
    today = datetime.now().date()
    if today != last_reset:
        daily_requests.clear()
        last_reset = today
    if is_premium(user_id):
        return True
    return daily_requests[user_id] < 30

def increment_daily(user_id):
    if not is_premium(user_id):
        daily_requests[user_id] += 1

def rate_limit(user_id):
    now = time.time()
    limit = 10 if is_premium(user_id) else 2
    per_seconds = 60
    user_commands[user_id] = [t for t in user_commands[user_id] if now - t < per_seconds]
    if len(user_commands[user_id]) >= limit:
        oldest = min(user_commands[user_id])
        wait_time = int(per_seconds - (now - oldest))
        return False, wait_time
    user_commands[user_id].append(now)
    return True, 0

# ========== ХРАНЕНИЕ СОСТОЯНИЙ ДЛЯ ПОИСКА ==========
user_search_states = {}

# ========== ФУНКЦИИ ПОИСКА ==========
def run_email_search(email):
    return f"📧 *Email:* {email}\nGoogle dorking:\nhttps://www.google.com/search?q=intext:{email}" + f"\n\nYandex:\nhttps://yandex.com/search/touch/?text={email}"

def run_nickname_search(username):
    import requests
    sites = {
        "TikTok": f"https://www.tiktok.com/@{username}",
        "Telegram": f"https://t.me/{username}",
        "GitHub": f"https://github.com/{username}",
        "YouTube": f"https://youtube.com/@{username}",
        "Snapchat": f"https://snapchat.com/add/{username}",
        "LinkedIn": f"https://linkedin.com/in/{username}",
        "Tumblr": f"https://{username}.tumblr.com",
        "Medium": f"https://medium.com/@{username}",
        "VK": f"https://vk.com/{username}",
        "Spotify": f"https://open.spotify.com/user/{username}",
        "Steam": f"https://steamcommunity.com/id/{username}",
        "Flickr": f"https://flickr.com/people/{username}",
        "Behance": f"https://behance.net/{username}",
        "Dribbble": f"https://dribbble.com/{username}",
        "ProductHunt": f"https://producthunt.com/@{username}",
        "GitLab": f"https://gitlab.com/{username}"
    }
    found = []
    for site_name, url in sites.items():
        try:
            r = requests.get(url, timeout=10, allow_redirects=True)
            text = r.text.lower()
            status = r.status_code
            exists = False
            if site_name == "Telegram":
                if "tgme_page_title" in r.text and "if you have telegram" not in text:
                    exists = True
            elif site_name == "TikTok":
                if status == 200:
                    error_signs = ["couldn't find", "page not found", "something went wrong", "this account doesn't exist", "user not found", "not found"]
                    success_signs = ["followers", "following", "подписчики", "подписки", "likes", "лайки"]
                    has_error = any(sign in text for sign in error_signs)
                    has_success = any(sign in text for sign in success_signs)
                    if not has_error and (has_success or len(text) > 5000):
                        exists = True
            elif site_name == "YouTube":
                if status == 200 and "this channel does not exist" not in text and "not found" not in text:
                    exists = True
            elif site_name == "VK":
                if status == 200 and "пользователь не найден" not in text and "user not found" not in text:
                    exists = True
            elif site_name == "Steam":
                if "the specified profile could not be found" not in text:
                    exists = True
            elif site_name == "Discord":
                if "sorry, nobody" not in text and "not found" not in text:
                    exists = True
            elif site_name in ["Instagram", "Twitter", "Facebook", "Pinterest", "Twitch", "Reddit", "LinkedIn"]:
                error_phrases = ["page not found", "sorry, this page isn't available", "this account doesn't exist", "this content isn't available", "we couldn't find that page", "sorry. unless you've got a time machine", "there doesn't seem to be anything here", "user not found"]
                if status == 200 and not any(phrase in text for phrase in error_phrases):
                    exists = True
            else:
                if status == 200:
                    exists = True
            if exists:
                found.append(f"✅ {site_name}: {url}")
        except:
            continue
    if found:
        return f"👤 *Никнейм:* {username}\n\n🔎 *НАЙДЕНО:*\n" + "\n".join(found[:30]) + f"\n\n🔍 *Google Dorking:*\nhttps:google.com/search?q=intext:{username}" + f"\n\nYandex:\nhttps://yandex.com/search/touch/?text={username}" + f"\nРасширенный поиск:\nhttps://whatsmyname.app"
    return f"👤 *Никнейм:* {username}\n\n❌ *Ничего не найдено*" + f"\n\n🔍 *Google Dorking:*\nhttps://www.google.com/search?q=intext:{username}" + f"\n\nYandex:\nhttps://yandex.com/search/touch/?text={username}" + f"\nРасширенный поиск:\nhttps://whatsmyname.app"

def run_ip_search(ip):
    import requests
    ip_pattern = re.compile(r'^(\d{1,3}\.){3}\d{1,3}$')
    if not ip_pattern.match(ip):
        return "❌ *Неверный формат IP-адреса*"
    try:
        response = requests.get(f"http://ip-api.com/json/{ip}", timeout=10)
        data = response.json()
        if data.get('status') != 'success':
            return f"❌ *Не удалось найти IP* {ip}"
        lat = data.get('lat', 0)
        lon = data.get('lon', 0)
        google_maps = f"https://www.google.com/maps?q={lat},{lon}"
        openstreetmap = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}&zoom=10"
        yandex_maps = f"https://yandex.com/maps/?pt={lon},{lat}&z=10"
        result = f"""🌐 *IP:* {ip}

━━━━━━━━━━━━━━━━
🌎 *ГЕОЛОКАЦИЯ*
━━━━━━━━━━━━━━━━
📍 *Страна:* {data.get('country', 'Неизвестно')}
🏙️ *Город:* {data.get('city', 'Неизвестно')}
🗺️ *Регион:* {data.get('regionName', 'Неизвестно')}
📌 *Координаты:* {lat}, {lon}
✈️ *Почтовый индекс:* {data.get('zip', 'Неизвестно')}

━━━━━━━━━━━━━━━━
🏢 *ПРОВАЙДЕР*
━━━━━━━━━━━━━━━━
📡 *ISP:* {data.get('isp', 'Неизвестно')}
💻 *Организация:* {data.get('org', 'Неизвестно')}
🔢 *AS:* {data.get('as', 'Неизвестно')}

━━━━━━━━━━━━━━━━
🗺️ *КАРТЫ*
━━━━━━━━━━━━━━━━
• Google Maps: {google_maps}
• OpenStreetMap: {openstreetmap}
• Yandex Maps: {yandex_maps}

━━━━━━━━━━━━━━━━
🕵️ *ДОПОЛНИТЕЛЬНО*
━━━━━━━━━━━━━━━━
• Временная зона: {data.get('timezone', 'Неизвестно')}"""
        return result
    except Exception as e:
        return f"❌ *Ошибка:* {e}"

def run_phone_search(phone):
    import requests
    phone_clean = re.sub(r'[^0-9+]', '', phone)
    result = f"📱 *Телефон:* {phone_clean}\n\n"
    result += f"• WhatsApp:\n https://wa.me/{phone_clean}\n"
    result += f"• Telegram:\n https://t.me/{phone_clean}\n"
    result += f"\n• Дополнительно: (google dorking)\nhttps://www.google.com/search?q=intext:{phone}\n"
    result += f"• Yandex:\nhttps://yandex.com/search/touch/?text={phone}\n"
    return result

def run_car_search(plate_number):
    import requests
    plate_clean = re.sub(r'[^A-Za-z0-9]', '', plate_number).upper()
    result = f"🚗 *Номер авто:* {plate_clean}\n\n"
    if re.match(r'^[A-Z]{1}\d{3}[A-Z]{2}\d{2,3}$', plate_clean):
        result += "🇷🇺 *РОССИЯ:*\n"
        result += f"• ГИБДД: https://xn--90adear.xn--p1ai/check/auto/{plate_clean}\n"
        result += f"• Автокод: https://avtokod.mos.ru/CheckCar/Index?number={plate_clean}\n"
    elif re.match(r'^[A-Z]{2}\d{4}[A-Z]{2}$', plate_clean):
        result += "🇺🇦 *УКРАИНА:*\n"
        result += f"• Опендатабот: https://opendatabot.ua/c/auto/{plate_clean}\n"
    elif re.match(r'^[A-Z]{1}\d{3}[A-Z]{3}$', plate_clean):
        result += "🇰🇿 *КАЗАХСТАН:*\n"
        result += f"• E-Gov: https://egov.kz/cms/ru/services/transport/check_vehicle_auto/{plate_clean}\n"
    else:
        result += "🌍 *МЕЖДУНАРОДНЫЙ ПОИСК:*\n"
    result += f"\n🔍 Google: https://www.google.com/search?q={plate_clean}+номер+авто\n"
    result += f"🔍 Avito: https://www.avito.ru/all?q={plate_clean}\n"
    return result

def run_photo_search():
    return """🔎 *ПОИСК ПО ФОТО*

🔗 *Сервисы для поиска:*

1. Yandex Images: https://yandex.com/images/
2. PimEyes: https://pimeyes.com
3. Bing Visual Search: https://www.bing.com/visualsearch

📌 *Инструкция:*
1. Откройте любой сервис
2. Нажмите на иконку камеры
3. Загрузите фото
4. Получите результаты"""

def get_simple_stats():
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT COUNT(*) FROM users WHERE last_active LIKE ?", (f"{today}%",))
    active_today = c.fetchone()[0]
    c.execute("SELECT user_id, last_active FROM users ORDER BY last_active DESC")
    users = c.fetchall()
    conn.close()
    result = f"""👥 *СТАТИСТИКА ПОЛЬЗОВАТЕЛЕЙ*

━━━━━━━━━━━━━━━━
📋 *ВСЕГО:* {total_users} пользователей
📈 *АКТИВНЫ СЕГОДНЯ:* {active_today}
━━━━━━━━━━━━━━━━

📃 *СПИСОК ПОЛЬЗОВАТЕЛЕЙ:*
"""
    for i, (user_id, last_active) in enumerate(users, 1):
        result += f"\n{i}. `{user_id}` - последний раз: {last_active[:19]}"
    return result

# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📧 Поиск по email", callback_data="search_email")],
        [InlineKeyboardButton(text="👤 Поиск по никнейму", callback_data="search_nickname")],
        [InlineKeyboardButton(text="🌐 Поиск по IP", callback_data="search_ip")],
        [InlineKeyboardButton(text="📱 Поиск по телефону", callback_data="search_phone")],
        [InlineKeyboardButton(text="🚗 Поиск по номеру авто", callback_data="search_car")],
        [InlineKeyboardButton(text="🖼️ Поиск по фото", callback_data="search_photo")],
        [InlineKeyboardButton(text="📊 Моя статистика", callback_data="my_stats")],
        [InlineKeyboardButton(text="💎 Купить Premium", callback_data="buy_premium")],
        [InlineKeyboardButton(text="🎫 Активировать промокод", callback_data="activate_promo")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="help_menu")]
    ])
    return keyboard

def get_back_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")]
    ])
    return keyboard

# ========== ОБРАБОТЧИКИ КОМАНД И КНОПОК ==========

@dp.message(Command("start"))
async def cmd_start(message: Message):
    welcome = """🤖 *Привет!*

Я *OSINT бот* для поиска информации в открытых источниках.
"""
    await message.answer(welcome, reply_markup=get_main_keyboard())

@dp.message(Command("menu"))
async def cmd_menu(message: Message):
    await message.answer("🔍 *Главное меню:*", reply_markup=get_main_keyboard())

@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("🔍 *Главное меню:*", reply_markup=get_main_keyboard())

@dp.callback_query(F.data == "help_menu")
async def help_menu(callback: CallbackQuery):
    await callback.answer()
    help_text = """❓ *ПОМОЩЬ ПО БОТУ*

━━━━━━━━━━━━━━━━
📚 *ОСНОВНЫЕ КОМАНДЫ:*
━━━━━━━━━━━━━━━━

🔍 `/email example@mail.com`
👤 `/nickname username`
🌐 `/ip 8.8.8.8`
📱 `/phone +380991234567`
🚗 `/car а123вв777`
🖼️ `/photo` - сервисы поиска фото
📊 `/stats` - моя статистика
💎 `/buy` - купить Premium
🎫 `/promo КОД` - активировать промокод

━━━━━━━━━━━━━━━━
⚠️ *ОГРАНИЧЕНИЯ:*
━━━━━━━━━━━━━━━━
• Бесплатно: до 2 запрос/мин, 30 в день
• Premium: до 10 запросов/мин, безлимит

━━━━━━━━━━━━━━━━
🤖 *OSINT Бот* | @tracergbot"""
    await callback.message.edit_text(help_text, reply_markup=get_back_keyboard())

@dp.callback_query(F.data == "my_stats")
async def my_stats(callback: CallbackQuery):
    await callback.answer()
    chat_id = callback.from_user.id
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM searches WHERE user_id = ?", (chat_id,))
    total = c.fetchone()[0]
    c.execute("SELECT type, COUNT(*) FROM searches WHERE user_id = ? GROUP BY type", (chat_id,))
    stats = c.fetchall()
    conn.close()
    stats_text = f"📝 *Ваша статистика*\n\n━━━━━━━━━━━━━━━━\n📈 *Всего поисков:* {total}\n━━━━━━━━━━━━━━━━\n\n"
    for stype, count in stats:
        emoji = {"email": "📧", "nickname": "👤", "ip": "🌐", "phone": "📱", "car": "🚗"}.get(stype, "🔍")
        stats_text += f"{emoji} *{stype}:* {count}\n"
    await callback.message.edit_text(stats_text, reply_markup=get_back_keyboard())

@dp.callback_query(F.data == "buy_premium")
async def buy_premium(callback: CallbackQuery):
    await callback.answer()
    chat_id = callback.from_user.id
    if is_premium(chat_id):
        await callback.message.edit_text("⭐ *У вас уже есть Premium!*\n✅ до 10 запросов в минуту\n✅ Безлимит запросов в день", reply_markup=get_back_keyboard())
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⭐ 1 месяц - 80 Stars ($1)", callback_data="premium_month")],
            [InlineKeyboardButton(text="⭐ Навсегда - 300 Stars ($5)", callback_data="premium_forever")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
        ])
        await callback.message.edit_text("💎 *Premium тарифы*\n\n• до 10 запросов/мин\n• Безлимит в день\n\n💰 *Цены:*\n• $1/месяц (80 Stars)\n• $5 навсегда (300 Stars)\n\nВыберите тариф:", reply_markup=keyboard)

@dp.callback_query(F.data == "activate_promo")
async def activate_promo(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("🎫 *Введите промокод* командой:\n`/promo КОД`\n\nПример: `/promo SUPER2024`", reply_markup=get_back_keyboard())

@dp.callback_query(F.data.startswith("search_"))
async def search_prompt(callback: CallbackQuery):
    await callback.answer()
    search_type = callback.data.replace("search_", "")
    user_id = callback.from_user.id
    
    # Сохраняем состояние пользователя
    user_search_states[user_id] = search_type
    
    prompts = {
        "email": "📧 *Введите email для поиска:*\n\nПример: `test@mail.com`",
        "nickname": "👤 *Введите никнейм для поиска:*\n\nПример: `username`",
        "ip": "🌐 *Введите IP адрес для поиска:*\n\nПример: `8.8.8.8`",
        "phone": "📱 *Введите номер телефона для поиска:*\n\nПример: `+380991234567`",
        "car": "🚗 *Введите номер автомобиля для поиска:*\n\nПример: `а123вв777`",
        "photo": "🖼️ *Поиск по фото*\n\n🔗 Сервисы для поиска:\n\n1. Yandex Images: https://yandex.com/images/\n2. PimEyes: https://pimeyes.com\n3. Bing Visual Search: https://www.bing.com/visualsearch"
    }
    
    if search_type == "photo":
        await callback.message.edit_text(prompts["photo"], reply_markup=get_back_keyboard())
    else:
        await callback.message.edit_text(prompts.get(search_type, "Введите данные для поиска:"), reply_markup=get_back_keyboard())

# ========== ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ (ПОИСК ПОСЛЕ КНОПКИ) ==========
@dp.message(F.text & ~F.text.startswith("/"))
async def handle_search_input(message: Message):
    user_id = message.from_user.id
    chat_id = user_id
    
    if user_id not in user_search_states:
        await message.answer("❌ *Пожалуйста, выберите тип поиска через меню*", reply_markup=get_main_keyboard())
        return
    
    search_type = user_search_states.pop(user_id)
    query_text = message.text.strip()
    
    # Проверка лимитов
    if not check_daily_limit(chat_id):
        await message.answer("❌ *Лимит 30 запросов в день исчерпан!*\n💎 Купите Premium: `/buy`")
        return
    
    allowed, wait_time = rate_limit(chat_id)
    if not allowed:
        await message.answer(f"⏳ *Слишком много запросов!* Подождите {wait_time} секунд.")
        return
    
    # Поиск
    status_msg = await message.answer(f"🔍 *Поиск...* ⏳")
    
    if search_type == "email":
        if "@" not in query_text:
            await status_msg.edit_text("❌ *Неверный формат email!*\nПример: `test@mail.com`")
            return
        result = await asyncio.to_thread(run_email_search, query_text)
    elif search_type == "nickname":
        result = await asyncio.to_thread(run_nickname_search, query_text)
    elif search_type == "ip":
        result = await asyncio.to_thread(run_ip_search, query_text)
    elif search_type == "phone":
        result = await asyncio.to_thread(run_phone_search, query_text)
    elif search_type == "car":
        result = await asyncio.to_thread(run_car_search, query_text)
    else:
        result = "❌ Неизвестный тип поиска"
    
    await status_msg.delete()
    await message.answer(result, reply_markup=get_back_keyboard())
    save_search(chat_id, search_type, query_text, result)
    increment_daily(chat_id)

# ========== ОБРАБОТКА ОТДЕЛЬНЫХ КОМАНД (для обратной совместимости) ==========
@dp.message(Command("email"))
async def cmd_email(message: Message):
    await message.answer("📧 *Используйте меню для поиска*", reply_markup=get_main_keyboard())

@dp.message(Command("nickname"))
async def cmd_nickname(message: Message):
    await message.answer("👤 *Используйте меню для поиска*", reply_markup=get_main_keyboard())

@dp.message(Command("ip"))
async def cmd_ip(message: Message):
    await message.answer("🌐 *Используйте меню для поиска*", reply_markup=get_main_keyboard())

@dp.message(Command("phone"))
async def cmd_phone(message: Message):
    await message.answer("📱 *Используйте меню для поиска*", reply_markup=get_main_keyboard())

@dp.message(Command("car"))
async def cmd_car(message: Message):
    await message.answer("🚗 *Используйте меню для поиска*", reply_markup=get_main_keyboard())

@dp.message(Command("photo"))
async def cmd_photo(message: Message):
    await message.answer(run_photo_search())

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    chat_id = message.from_user.id
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM searches WHERE user_id = ?", (chat_id,))
    total = c.fetchone()[0]
    c.execute("SELECT type, COUNT(*) FROM searches WHERE user_id = ? GROUP BY type", (chat_id,))
    stats = c.fetchall()
    conn.close()
    stats_text = f"📝 *Ваша статистика*\n\n━━━━━━━━━━━━━━━━\n📈 *Всего поисков:* {total}\n━━━━━━━━━━━━━━━━\n\n"
    for stype, count in stats:
        emoji = {"email": "📧", "nickname": "👤", "ip": "🌐", "phone": "📱", "car": "🚗"}.get(stype, "🔍")
        stats_text += f"{emoji} *{stype}:* {count}\n"
    await message.answer(stats_text, reply_markup=get_back_keyboard())

@dp.message(Command("premium"))
@dp.message(Command("buy"))
async def cmd_buy(message: Message):
    chat_id = message.from_user.id
    if is_premium(chat_id):
        await message.answer("⭐ *У вас уже есть Premium!*\n✅ до 10 запросов в минуту\n✅ Безлимит запросов в день", reply_markup=get_back_keyboard())
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⭐ 1 месяц - 80 Stars ($1)", callback_data="premium_month")],
            [InlineKeyboardButton(text="⭐ Навсегда - 300 Stars ($5)", callback_data="premium_forever")]
        ])
        await message.answer("💎 *Premium тарифы*\n\n• до 10 запросов/мин\n• Безлимит в день\n\n💰 *Цены:*\n• $1/месяц (80 Stars)\n• $5 навсегда (300 Stars)\n\nВыберите тариф:", reply_markup=keyboard)

@dp.message(Command("promo"))
async def cmd_promo(message: Message):
    code = message.text.replace("/promo", "").strip()
    chat_id = message.from_user.id
    if not code:
        await message.answer("❌ Использование: `/promo КОД`")
        return
    result = use_promocode(code)
    if result == "expired":
        await message.answer("❌ Промокод использован максимальное количество раз")
    elif result == "month":
        add_premium(chat_id, days=30)
        await message.answer("🎫 *Промокод активирован!*\n⭐ Premium на 1 месяц активирован!\n\n✅ до 10 запросов в минуту\n✅ Безлимит запросов в день")
    elif result == "forever":
        add_premium(chat_id, forever=True)
        await message.answer("🎫 *Промокод активирован!*\n⭐ Premium НАВСЕГДА активирован!\n\n✅ до 10 запросов в минуту\n✅ Безлимит запросов в день")
    else:
        await message.answer("❌ Неверный промокод")

# ========== АДМИН КОМАНДЫ ==========
@dp.message(Command("users"))
async def cmd_users(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Только для администратора")
        return
    result = get_simple_stats()
    await message.answer(result)

@dp.message(Command("backup"))
async def cmd_backup(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Только для администратора")
        return
    if os.path.exists('bot_database.db'):
        file = FSInputFile('bot_database.db')
        await message.answer_document(file, caption="✅ Бэкап базы данных")
    else:
        await message.answer("❌ Файл базы не найден")

@dp.message(Command("activate_month"))
async def cmd_activate_month(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Только для администратора")
        return
    parts = message.text.split()
    if len(parts) >= 2:
        user_id = int(parts[1])
        add_premium(user_id, days=30)
        await message.answer(f"✅ Премиум на МЕСЯЦ активирован для `{user_id}`")
        await bot.send_message(user_id, "⭐ Вам активирован Premium на 1 месяц!\n\n✅ до 10 запросов в минуту\n✅ Безлимит запросов в день")
    else:
        await message.answer("❌ Использование: `/activate_month 123456789`")

@dp.message(Command("activate_forever"))
async def cmd_activate_forever(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Только для администратора")
        return
    parts = message.text.split()
    if len(parts) >= 2:
        user_id = int(parts[1])
        add_premium(user_id, forever=True)
        await message.answer(f"✅ Премиум НАВСЕГДА активирован для `{user_id}`")
        await bot.send_message(user_id, "⭐ Вам активирован Premium НАВСЕГДА!\n\n✅ до 10 запросов в минуту\n✅ Безлимит запросов в день")
    else:
        await message.answer("❌ Использование: `/activate_forever 123456789`")

@dp.message(Command("add_promo"))
async def cmd_add_promo(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Только для администратора")
        return
    parts = message.text.split()
    if len(parts) >= 4:
        code = parts[1]
        promo_type = parts[2]
        uses = int(parts[3])
        if promo_type not in ["month", "forever"]:
            await message.answer("❌ Тип должен быть: `month` или `forever`")
            return
        add_promocode(code, promo_type, uses)
        await message.answer(f"✅ Промокод `{code}` добавлен!\nТип: {promo_type}\nИспользований: {uses}")
    else:
        await message.answer("❌ Использование: `/add_promo КОД month/forever кол-во`")

@dp.message(Command("del_promo"))
async def cmd_del_promo(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Только для администратора")
        return
    parts = message.text.split()
    if len(parts) >= 2:
        code = parts[1]
        if code in promocodes:
            remove_promocode(code)
            await message.answer(f"✅ Промокод `{code}` удален!")
        else:
            await message.answer(f"❌ Промокод `{code}` не найден")
    else:
        await message.answer("❌ Использование: `/del_promo КОД`")

@dp.message(Command("list_promo"))
async def cmd_list_promo(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("❌ Только для администратора")
        return
    if not promocodes:
        await message.answer("📭 Нет активных промокодов")
        return
    result = "🎫 *СПИСОК ПРОМОКОДОВ*\n\n"
    for code, data in promocodes.items():
        result += f"`{code}` - {data['type']} - использовано {data['used']}/{data['uses']}\n"
    await message.answer(result)

# ========== ОБРАБОТКА КНОПОК PREMIUM ОПЛАТА ==========
@dp.callback_query(F.data.in_({"premium_month", "premium_forever"}))
async def process_premium_callback(callback: CallbackQuery):
    await callback.answer()
    chat_id = callback.from_user.id
    data = callback.data
    
    import requests
    if data == "premium_month":
        url = f"https://api.telegram.org/bot{TOKEN}/createInvoiceLink"
        payload = {
            "title": "Premium 1 месяц",
            "description": "до 10 запросов/мин, безлимит в день",
            "payload": f"month_{chat_id}",
            "currency": "XTR",
            "prices": [{"label": "Premium 1 месяц", "amount": 80}]
        }
        resp = requests.post(url, json=payload).json()
        if resp.get("ok"):
            await callback.message.answer(f"💎 *Оплатите по ссылке:*\n{resp['result']}\n\nПосле оплаты Premium активируется автоматически!")
        else:
            await callback.message.answer("❌ Ошибка создания счета. Попробуйте позже.")
    elif data == "premium_forever":
        url = f"https://api.telegram.org/bot{TOKEN}/createInvoiceLink"
        payload = {
            "title": "Premium НАВСЕГДА",
            "description": "до 10 запросов/мин, безлимит в день",
            "payload": f"forever_{chat_id}",
            "currency": "XTR",
            "prices": [{"label": "Premium НАВСЕГДА", "amount": 300}]
        }
        resp = requests.post(url, json=payload).json()
        if resp.get("ok"):
            await callback.message.answer(f"💎 *Оплатите по ссылке:*\n{resp['result']}\n\nПосле оплаты Premium активируется автоматически!")
        else:
            await callback.message.answer("❌ Ошибка создания счета. Попробуйте позже.")

# ========== ОБРАБОТКА УСПЕШНЫХ ПЛАТЕЖЕЙ ==========
@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    user_id = message.from_user.id
    if payload.startswith("month_"):
        add_premium(user_id, days=30)
        await message.answer("⭐ *Premium на 1 месяц активирован!*\n\n✅ до 10 запросов в минуту\n✅ Безлимит запросов в день")
        for admin_id in ADMIN_IDS:
            await bot.send_message(admin_id, f"💰 Пользователь `{user_id}` купил Premium на МЕСЯЦ через Stars")
    elif payload.startswith("forever_"):
        add_premium(user_id, forever=True)
        await message.answer("⭐ *Premium НАВСЕГДА активирован!*\n\n✅ до 10 запросов в минуту\n✅ Безлимит запросов в день")
        for admin_id in ADMIN_IDS:
            await bot.send_message(admin_id, f"💰 Пользователь `{user_id}` купил Premium НАВСЕГДА через Stars")

# ========== ОБРАБОТКА ДОКУМЕНТОВ (БЭКАП) ==========
@dp.message(F.document)
async def handle_document(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    doc = message.document
    if doc.file_name == "bot_database.db":
        file_id = doc.file_id
        file = await bot.get_file(file_id)
        file_path = file.file_path
        import requests
        file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
        response = requests.get(file_url)
        with open("bot_database.db", "wb") as f:
            f.write(response.content)
        await message.answer("✅ База данных восстановлена из бэкапа!")

# ========== РЕГИСТРАЦИЯ ПОЛЬЗОВАТЕЛЯ ==========
@dp.message()
async def register_user(message: Message):
    chat_id = message.from_user.id
    username = message.from_user.first_name or "Пользователь"
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users VALUES (?, ?, ?)",
              (chat_id, datetime.now().isoformat(), datetime.now().isoformat()))
    c.execute("UPDATE users SET last_active = ? WHERE user_id = ?",
              (datetime.now().isoformat(), chat_id))
    conn.commit()
    conn.close()

# ========== ЗАПУСК ==========
async def main():
    print("🤖 Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
