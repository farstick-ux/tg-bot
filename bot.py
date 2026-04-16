import requests
import subprocess
import time
import re
import threading
import os
import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict
from flask import Flask

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [6695578489]  # Твой ID

if not TOKEN:
    print("❌ Ошибка: BOT_TOKEN не найден в переменных окружения!")
    exit(1)
URL = f"https://api.telegram.org/bot{TOKEN}/"

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

# ========== KEEP ALIVE ==========
def keep_alive():
    while True:
        time.sleep(300)
        try:
            requests.get("https://tracergbot.onrender.com", timeout=5)
            print("Пинг отправлен")
        except:
            pass

threading.Thread(target=keep_alive, daemon=True).start()

# ========== ФУНКЦИЯ "ПЕЧАТАЕТ..." ==========
def send_action(chat_id, action="typing"):
    try:
        requests.post(URL + "sendChatAction", 
                      json={"chat_id": chat_id, "action": action}, timeout=5)
    except:
        pass

def send_message(chat_id, text, parse_mode=None, reply_markup=None):
    try:
        data = {"chat_id": chat_id, "text": text}
        if parse_mode:
            data["parse_mode"] = parse_mode
        if reply_markup:
            data["reply_markup"] = reply_markup
        if len(text) > 4000:
            for i in range(0, len(text), 4000):
                data["text"] = text[i:i+4000]
                requests.post(URL + "sendMessage", json=data, timeout=10)
        else:
            requests.post(URL + "sendMessage", json=data, timeout=10)
    except Exception as e:
        print(f"Ошибка отправки: {e}")

def get_updates(offset=None):
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    try:
        response = requests.get(URL + "getUpdates", params=params, timeout=35)
        return response.json()
    except:
        return {"result": []}

# ========== АДМИН СТАТИСТИКА ==========
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

# ========== БЭКАП ==========
def backup_to_telegram(chat_id):
    try:
        if os.path.exists('bot_database.db'):
            files = {'document': open('bot_database.db', 'rb')}
            requests.post(URL + "sendDocument", 
                         data={'chat_id': chat_id},
                         files=files)
            return True
    except:
        pass
    return False

# ========== ФУНКЦИИ ПОИСКА ==========
def run_email_search(email):
    try:
        result = subprocess.run(["holehe", email, "--no-color"], capture_output=True, text=True, timeout=60)
        clean = re.sub(r'\x1b\[[0-9;]*m', '', result.stdout)
        found_sites = []
        for line in clean.split("\n"):
            if "[+]" in line:
                site = line.replace("[+]", "").strip()
                site = re.sub(r'https?://', '', site)
                site = site.split()[0] if site.split() else site
                if len(site) > 3 and site.lower() not in ['email', 'mail']:
                    found_sites.append(f"✅ {site[:100]}")
        if found_sites:
            return f"📧 *Email:* {email}\n\n🔎 *НАЙДЕНО:*\n" + "\n".join(found_sites[:100]) + f"\n\nДополнительно: (google dorking)\nhttps://www.google.com/search?q={email}+filetype:xls+OR+filetype:txt+OR+filetype:pdf" + f"\n\nYandex:\nhttps://yandex.com/search/touch/?text={email}"
        return f"📧 *Email:* {email}\n\n❌ *Ничего не найдено*\n\nДополнительно: (google dorking)\nhttps://www.google.com/search?q={email}+filetype:xls+OR+filetype:txt+OR+filetype:pdf" + f"\n\nYandex:\nhttps://yandex.com/search/touch/?text={email}"
    except Exception as e:
        return f"❌ *Ошибка:* {e}"

def run_nickname_search(username):
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
        return f"👤 *Никнейм:* {username}\n\n🔎 *НАЙДЕНО:*\n" + "\n".join(found[:30]) + f"\n\n🔍 *Google Dorking:*\nhttps://www.google.com/search?q=intext:{username}" + f"\n\nYandex:\nhttps://yandex.com/search/touch/?text={username}"
    return f"👤 *Никнейм:* {username}\n\n❌ *Ничего не найдено*" + f"\n\n🔍 *Google Dorking:*\nhttps://www.google.com/search?q=intext:{username}" + f"\n\nYandex:\nhttps://yandex.com/search/touch/?text={username}"

def run_ip_search(ip):
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
    phone_clean = re.sub(r'[^0-9+]', '', phone)
    result = f"📱 *Телефон:* {phone_clean}\n\n"
    result += f"• WhatsApp:\n https://wa.me/{phone_clean}\n"
    result += f"• Telegram:\n https://t.me/{phone_clean}\n"
    result += f"• Google:\n https://www.google.com/search?q={phone_clean}\n"
    result += f"\n• Дополнительно: (google dorking)\nhttps://www.google.com/search?q={phone}+filetype:xls+OR+filetype:txt\n"
    result += f"• Yandex:\nhttps://yandex.com/search/touch/?text={phone}\n"
    return result

def run_car_search(plate_number):
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

# ========== КОМАНДЫ ==========
def handle_command(chat_id, text, username):
    # Дневной лимит
    if not check_daily_limit(chat_id):
        send_message(chat_id, "❌ *Лимит 40 запросов в день исчерпан!*\n💎 Купите Premium: `/buy`", parse_mode="Markdown")
        return
    
    # Rate limit
    allowed, wait_time = rate_limit(chat_id)
    if not allowed:
        send_message(chat_id, f"⏳ *Слишком много запросов!* Подождите {wait_time} секунд.", parse_mode="Markdown")
        return

    # --- АДМИН КОМАНДЫ ---
    if chat_id in ADMIN_IDS:
        if text == "/users":
            result = get_simple_stats()
            send_message(chat_id, result, parse_mode="Markdown")
            return
        if text == "/backup":
            if backup_to_telegram(chat_id):
                send_message(chat_id, "✅ Бэкап отправлен!")
            else:
                send_message(chat_id, "❌ Ошибка бэкапа")
            return
        if text.startswith("/activate_month"):
            parts = text.split()
            if len(parts) >= 2:
                user_id = int(parts[1])
                add_premium(user_id, days=30)
                send_message(chat_id, f"✅ Премиум на МЕСЯЦ активирован для `{user_id}`")
                send_message(user_id, "⭐ Вам активирован Premium на 1 месяц!\n\n✅ 10 запросов в минуту\n✅ Безлимит запросов в день")
            else:
                send_message(chat_id, "❌ Использование: `/activate_month 123456789`", parse_mode="Markdown")
            return
        if text.startswith("/activate_forever"):
            parts = text.split()
            if len(parts) >= 2:
                user_id = int(parts[1])
                add_premium(user_id, forever=True)
                send_message(chat_id, f"✅ Премиум НАВСЕГДА активирован для `{user_id}`")
                send_message(user_id, "⭐ Вам активирован Premium НАВСЕГДА!\n\n✅ 10 запросов в минуту\n✅ Безлимит запросов в день")
            else:
                send_message(chat_id, "❌ Использование: `/activate_forever 123456789`", parse_mode="Markdown")
            return
        
        # ПРОМОКОДЫ (только админ)
        if text.startswith("/add_promo"):
            parts = text.split()
            if len(parts) >= 4:
                code = parts[1]
                promo_type = parts[2]
                uses = int(parts[3])
                if promo_type not in ["month", "forever"]:
                    send_message(chat_id, "❌ Тип должен быть: `month` или `forever`", parse_mode="Markdown")
                    return
                add_promocode(code, promo_type, uses)
                send_message(chat_id, f"✅ Промокод `{code}` добавлен!\nТип: {promo_type}\nИспользований: {uses}", parse_mode="Markdown")
            else:
                send_message(chat_id, "❌ Использование: `/add_promo КОД month/forever кол-во`", parse_mode="Markdown")
            return
        
        if text.startswith("/del_promo"):
            parts = text.split()
            if len(parts) >= 2:
                code = parts[1]
                if code in promocodes:
                    remove_promocode(code)
                    send_message(chat_id, f"✅ Промокод `{code}` удален!", parse_mode="Markdown")
                else:
                    send_message(chat_id, f"❌ Промокод `{code}` не найден", parse_mode="Markdown")
            else:
                send_message(chat_id, "❌ Использование: `/del_promo КОД`", parse_mode="Markdown")
            return
        
        if text == "/list_promo":
            if not promocodes:
                send_message(chat_id, "📭 Нет активных промокодов")
                return
            result = "🎫 *СПИСОК ПРОМОКОДОВ*\n\n"
            for code, data in promocodes.items():
                result += f"`{code}` - {data['type']} - использовано {data['used']}/{data['uses']}\n"
            send_message(chat_id, result, parse_mode="Markdown")
            return

    # --- ОБЫЧНЫЕ КОМАНДЫ ---
    if text == "/start":
        welcome = """🤖 *Привет!*

Я *OSINT бот* для поиска информации в открытых источниках.

━━━━━━━━━━━━━━━━
🔍 *ДОСТУПНЫЕ КОМАНДЫ:*
━━━━━━━━━━━━━━━━

📧 `/email` - поиск по email
👤 `/nickname` - поиск по никнейму
🌐 `/ip` - информация об IP
📱 `/phone` - поиск по телефону
🚗 `/car` - поиск по номеру авто
🖼️ `/photo` - поиск по фото
📊 `/stats` - моя статистика
💎 `/buy` - купить Premium
🎫 `/promo` - активировать промокод
❓ `/help` - помощь

━━━━━━━━━━━━━━━━
💡 *Пример:* `/email test@mail.com`"""
        send_message(chat_id, welcome, parse_mode="Markdown")
    
    elif text == "/help":
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
        send_message(chat_id, help_text, parse_mode="Markdown")
    
    elif text == "/photo":
        send_action(chat_id, "typing")
        time.sleep(0.5)
        result = run_photo_search()
        send_message(chat_id, result, parse_mode="Markdown")
    
    elif text == "/stats":
        send_action(chat_id, "typing")
        time.sleep(0.5)
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
        send_message(chat_id, stats_text, parse_mode="Markdown")
    
    elif text == "/premium" or text == "/buy":
        if is_premium(chat_id):
            send_message(chat_id, "⭐ *У вас уже есть Premium!*\n✅ до 10 запросов в минуту\n✅ Безлимит запросов в день", parse_mode="Markdown")
        else:
            keyboard = {
                "inline_keyboard": [
                    [{"text": "⭐ 1 месяц - 80 Stars ($1)", "callback_data": "premium_month"}],
                    [{"text": "⭐ Навсегда - 300 Stars ($5)", "callback_data": "premium_forever"}]
                ]
            }
            send_message(chat_id, "💎 *Premium тарифы*\n\n• до 10 запросов/мин\n• Безлимит в день\n\n💰 *Цены:*\n• $1/месяц (80 Stars)\n• $5 навсегда (300 Stars)\n\nВыберите тариф:", parse_mode="Markdown", reply_markup=keyboard)
    
    elif text.startswith("/promo"):
        code = text.replace("/promo", "").strip()
        if not code:
            send_message(chat_id, "❌ Использование: `/promo КОД`", parse_mode="Markdown")
            return
        result = use_promocode(code)
        if result == "expired":
            send_message(chat_id, "❌ Промокод использован максимальное количество раз", parse_mode="Markdown")
        elif result == "month":
            add_premium(chat_id, days=30)
            send_message(chat_id, "🎫 *Промокод активирован!*\n⭐ Premium на 1 месяц активирован!\n\n✅ до 10 запросов в минуту\n✅ Безлимит запросов в день", parse_mode="Markdown")
        elif result == "forever":
            add_premium(chat_id, forever=True)
            send_message(chat_id, "🎫 *Промокод активирован!*\n⭐ Premium НАВСЕГДА активирован!\n\n✅ до 10 запросов в минуту\n✅ Безлимит запросов в день", parse_mode="Markdown")
        else:
            send_message(chat_id, "❌ Неверный промокод", parse_mode="Markdown")
    
    elif text.startswith("/email"):
        email = text.replace("/email", "").strip()
        if email and "@" in email:
            send_action(chat_id, "typing")
            send_message(chat_id, f"🔍 *Поиск email:* {email}\n⏳ *Подождите, ищу...*", parse_mode="Markdown")
            result = run_email_search(email)
            send_message(chat_id, result, parse_mode="Markdown")
            save_search(chat_id, "email", email, result)
            increment_daily(chat_id)
        else:
            send_message(chat_id, "❌ *Использование:* `/email email@example.com`", parse_mode="Markdown")
    
    elif text.startswith("/nickname"):
        nickname = text.replace("/nickname", "").strip()
        if nickname:
            send_action(chat_id, "typing")
            send_message(chat_id, f"🔍 *Поиск никнейма:* {nickname}\n⏳ *Подождите, ищу...*", parse_mode="Markdown")
            result = run_nickname_search(nickname)
            send_message(chat_id, result, parse_mode="Markdown")
            save_search(chat_id, "nickname", nickname, result)
            increment_daily(chat_id)
        else:
            send_message(chat_id, "❌ *Использование:* `/nickname username`", parse_mode="Markdown")
    
    elif text.startswith("/ip"):
        ip = text.replace("/ip", "").strip()
        if ip:
            send_action(chat_id, "typing")
            send_message(chat_id, f"🌐 *Поиск IP:* {ip}\n⏳ *Подождите, ищу...*", parse_mode="Markdown")
            result = run_ip_search(ip)
            send_message(chat_id, result, parse_mode="Markdown")
            save_search(chat_id, "ip", ip, result)
            increment_daily(chat_id)
        else:
            send_message(chat_id, "❌ *Использование:* `/ip 8.8.8.8`", parse_mode="Markdown")
    
    elif text.startswith("/phone"):
        phone = text.replace("/phone", "").strip()
        if phone:
            send_action(chat_id, "typing")
            send_message(chat_id, f"📱 *Поиск телефона:* {phone}\n⏳ *Подождите, ищу...*", parse_mode="Markdown")
            result = run_phone_search(phone)
            send_message(chat_id, result, parse_mode="Markdown")
            save_search(chat_id, "phone", phone, result)
            increment_daily(chat_id)
        else:
            send_message(chat_id, "❌ *Использование:* `/phone +380991234567`", parse_mode="Markdown")
    
    elif text.startswith("/car"):
        car = text.replace("/car", "").strip()
        if car:
            send_action(chat_id, "typing")
            send_message(chat_id, f"🚗 *Поиск авто:* {car}\n⏳ *Подождите, ищу...*", parse_mode="Markdown")
            result = run_car_search(car)
            send_message(chat_id, result, parse_mode="Markdown")
            save_search(chat_id, "car", car, result)
            increment_daily(chat_id)
        else:
            send_message(chat_id, "❌ *Использование:* `/car а123вв777`", parse_mode="Markdown")
    
    else:
        send_message(chat_id, "❌ *Неизвестная команда.* Используйте `/help`", parse_mode="Markdown")

# ========== ОБРАБОТКА КНОПОК (PREMIUM ОПЛАТА) ==========
def handle_callback_query(callback_query):
    callback_id = callback_query["id"]
    chat_id = callback_query["message"]["chat"]["id"]
    data = callback_query["data"]
    
    requests.post(URL + "answerCallbackQuery", json={"callback_query_id": callback_id})
    
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
            send_message(chat_id, f"💎 *Оплатите по ссылке:*\n{resp['result']}\n\nПосле оплаты Premium активируется автоматически!", parse_mode="Markdown")
        else:
            send_message(chat_id, "❌ Ошибка создания счета. Попробуйте позже.", parse_mode="Markdown")
    
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
            send_message(chat_id, f"💎 *Оплатите по ссылке:*\n{resp['result']}\n\nПосле оплаты Premium активируется автоматически!", parse_mode="Markdown")
        else:
            send_message(chat_id, "❌ Ошибка создания счета. Попробуйте позже.", parse_mode="Markdown")

# ========== ЗАПУСК FLASK ==========
flask_app = Flask(__name__)

@flask_app.route('/')
def health_check():
    return "Bot is running!", 200

def run_flask():
    flask_app.run(host='0.0.0.0', port=10000)

threading.Thread(target=run_flask, daemon=True).start()
print("✅ Flask запущен!")

# ========== ОСНОВНОЙ ЦИКЛ ==========
print("🤖 Бот запущен...")
last_id = 0

while True:
    try:
        updates = get_updates(last_id + 1)
        
        for update in updates.get("result", []):
            last_id = update["update_id"]
            
            if "callback_query" in update:
                handle_callback_query(update["callback_query"])
                continue
            
            if "message" in update and "successful_payment" in update["message"]:
                payment = update["message"]["successful_payment"]
                payload = payment["invoice_payload"]
                user_id = update["message"]["chat"]["id"]
                if payload.startswith("month_"):
                    add_premium(user_id, days=30)
                    send_message(user_id, "⭐ *Premium на 1 месяц активирован!*\n\n✅ до 10 запросов в минуту\n✅ Безлимит запросов в день", parse_mode="Markdown")
                    for admin_id in ADMIN_IDS:
                        send_message(admin_id, f"💰 Пользователь `{user_id}` купил Premium на МЕСЯЦ через Stars", parse_mode="Markdown")
                elif payload.startswith("forever_"):
                    add_premium(user_id, forever=True)
                    send_message(user_id, "⭐ *Premium НАВСЕГДА активирован!*\n\n✅ до 10 запросов в минуту\n✅ Безлимит запросов в день", parse_mode="Markdown")
                    for admin_id in ADMIN_IDS:
                        send_message(admin_id, f"💰 Пользователь `{user_id}` купил Premium НАВСЕГДА через Stars", parse_mode="Markdown")
                continue
            
            if "message" not in update:
                continue
            
            chat_id = update["message"]["chat"]["id"]
            text = update["message"].get("text", "")
            username = update["message"].get("from", {}).get("first_name", "Пользователь")
            
            if "document" in update["message"]:
                doc = update["message"]["document"]
                file_name = doc.get("file_name", "")
                if file_name == "bot_database.db" and chat_id in ADMIN_IDS:
                    file_id = doc["file_id"]
                    file_info = requests.get(URL + "getFile", params={"file_id": file_id}).json()
                    file_path = file_info["result"]["file_path"]
                    file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
                    response = requests.get(file_url)
                    with open("bot_database.db", "wb") as f:
                        f.write(response.content)
                    send_message(chat_id, "✅ База данных восстановлена из бэкапа!")
                continue
            
            conn = sqlite3.connect('bot_database.db')
            c = conn.cursor()
            c.execute("INSERT OR IGNORE INTO users VALUES (?, ?, ?)",
                      (chat_id, datetime.now().isoformat(), datetime.now().isoformat()))
            c.execute("UPDATE users SET last_active = ? WHERE user_id = ?",
                      (datetime.now().isoformat(), chat_id))
            conn.commit()
            conn.close()
            
            handle_command(chat_id, text, username)
        
        time.sleep(1)
        
    except Exception as e:
        print(f"Ошибка: {e}")
        time.sleep(5)
