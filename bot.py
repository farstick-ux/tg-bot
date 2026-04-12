import requests
import subprocess
import time
import re
import threading
import os
import sqlite3
from datetime import datetime
from collections import defaultdict

TOKEN = os.getenv("BOT_TOKEN")

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

# ========== RATE LIMITING ==========
user_commands = defaultdict(list)

def rate_limit(user_id, limit=10, per_seconds=60):
    now = time.time()
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

def send_message(chat_id, text):
    try:
        if len(text) > 4000:
            for i in range(0, len(text), 4000):
                requests.post(URL + "sendMessage", json={"chat_id": chat_id, "text": text[i:i+4000]}, timeout=10)
        else:
            requests.post(URL + "sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)
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
                    found_sites.append(f"✅ {site[:50]}")
        if found_sites:
            return f"🔍 Email: {email}\n\n✅ НАЙДЕНО:\n" + "\n".join(found_sites[:20])
        return f"🔍 Email: {email}\n\n❌ Ничего не найдено"
    except Exception as e:
        return f"❌ Ошибка: {e}"

def run_nickname_search(username):
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
    for site_name, url in sites.items():
        try:
            r = requests.get(url, timeout=5, allow_redirects=False)
            if r.status_code == 200:
                if site_name == "Telegram":
                    if "tgme_page_title" in r.text and "If you have Telegram" not in r.text:
                        found.append(f"✅ {site_name}: {url}")
                else:
                    found.append(f"✅ {site_name}: {url}")
        except:
            pass
    if found:
        return f"🔍 НИКНЕЙМ: {username}\n\n" + "\n".join(found)
    return f"🔍 По никнейму {username} ничего не найдено"

def run_ip_search(ip):
    ip_pattern = re.compile(r'^(\d{1,3}\.){3}\d{1,3}$')
    if not ip_pattern.match(ip):
        return "❌ Неверный формат IP-адреса"
    try:
        response = requests.get(f"http://ip-api.com/json/{ip}", timeout=10)
        data = response.json()
        if data.get('status') == 'success':
            return f"""🌐 IP: {ip}

📍 Страна: {data.get('country', 'Неизвестно')}
🏙️ Город: {data.get('city', 'Неизвестно')}
🏢 Провайдер: {data.get('isp', 'Неизвестно')}
🗺️ Координаты: {data.get('lat')}, {data.get('lon')}"""
        return f"❌ Не удалось найти IP {ip}"
    except Exception as e:
        return f"❌ Ошибка: {e}"

def run_phone_search(phone):
    phone_clean = re.sub(r'[^0-9+]', '', phone)
    result = f"📱 ТЕЛЕФОН: {phone_clean}\n\n"
    result += f"• WhatsApp: https://wa.me/{phone_clean}\n"
    result += f"• Telegram: https://t.me/{phone_clean}\n"
    result += f"• Google: https://www.google.com/search?q={phone_clean}\n"
    return result

def run_car_search(plate_number):
    plate_clean = re.sub(r'[^A-Za-z0-9]', '', plate_number).upper()
    result = f"🚗 НОМЕР АВТО: {plate_clean}\n\n"
    
    if re.match(r'^[A-Z]{1}\d{3}[A-Z]{2}\d{2,3}$', plate_clean):
        result += "🇷🇺 РОССИЯ:\n"
        result += f"• ГИБДД: https://xn--90adear.xn--p1ai/check/auto/{plate_clean}\n"
        result += f"• Автокод: https://avtokod.mos.ru/CheckCar/Index?number={plate_clean}\n"
    elif re.match(r'^[A-Z]{2}\d{4}[A-Z]{2}$', plate_clean):
        result += "🇺🇦 УКРАИНА:\n"
        result += f"• Опендатабот: https://opendatabot.ua/c/auto/{plate_clean}\n"
    elif re.match(r'^[A-Z]{1}\d{3}[A-Z]{3}$', plate_clean):
        result += "🇰🇿 КАЗАХСТАН:\n"
        result += f"• E-Gov: https://egov.kz/cms/ru/services/transport/check_vehicle_auto/{plate_clean}\n"
    else:
        result += "🌍 МЕЖДУНАРОДНЫЙ ПОИСК:\n"
    
    result += f"\n🔍 Google: https://www.google.com/search?q={plate_clean}+номер+авто\n"
    result += f"🔍 Avito: https://www.avito.ru/all?q={plate_clean}\n"
    return result

def run_photo_search():
    return """🔎 ПОИСК ПО ФОТО

🔗 СЕРВИСЫ ДЛЯ ПОИСКА:

1. Google Search: https://google.com
2. Yandex Images: https://yandex.com/images/
3. PimEyes: https://pimeyes.com
4. Bing Visual Search: https://www.bing.com/visualsearch

📌 Инструкция:
1. Откройте любой сервис
2. Нажмите на иконку камеры
3. Загрузите фото
4. Получите результаты"""

# ========== КОМАНДЫ ==========
def handle_command(chat_id, text, username):
    # Rate limiting
    allowed, wait_time = rate_limit(chat_id)
    if not allowed:
        send_message(chat_id, f"⏳ Слишком много запросов! Подождите {wait_time} секунд.")
        return
    
    if text == "/start":
        welcome = f"""🤖 Привет!

Я OSINT бот для поиска информации.

🔍 Команды:
/email <email> - поиск по email
/nickname <ник> - поиск по никнейму
/ip <айпи> - поиск по IP
/phone <номер> - поиск по телефону
/car <номер> - поиск по номеру авто
/photo - поиск по фото
/help - помощь
/stats - моя статистика"""
        
        
        send_message(chat_id, welcome)
    
    elif text == "/help":
        help_text = """📚 *ПОМОЩЬ*

*Команды:*
/email example@mail.com - поиск email
/nickname username - поиск никнейма
/ip 8.8.8.8 - поиск IP
/phone +380991234567 - поиск телефона
/car а123вв777 - поиск авто
/photo - сервисы поиска фото
/stats - моя статистика

*Ограничения:* 10 запросов в минуту"""
        send_message(chat_id, help_text)
    
    elif text == "/photo":
        result = run_photo_search()
        send_message(chat_id, result)
    
    elif text == "/stats":
        conn = sqlite3.connect('bot_database.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM searches WHERE user_id = ?", (chat_id,))
        total = c.fetchone()[0]
        c.execute("SELECT type, COUNT(*) FROM searches WHERE user_id = ? GROUP BY type", (chat_id,))
        stats = c.fetchall()
        conn.close()
        
        stats_text = f"📊 *Ваша статистика*\n\nВсего поисков: {total}\n\n"
        for stype, count in stats:
            emoji = {"email": "📧", "nickname": "👤", "ip": "🌐", "phone": "📱", "car": "🚗"}.get(stype, "🔍")
            stats_text += f"{emoji} {stype}: {count}\n"
        send_message(chat_id, stats_text)
    
    elif text.startswith("/email"):
        email = text.replace("/email", "").strip()
        if email and "@" in email:
            send_message(chat_id, f"🔍 Поиск email: {email}\n⏳ Подождите...")
            result = run_email_search(email)
            send_message(chat_id, result)
            save_search(chat_id, "email", email, result)
        else:
            send_message(chat_id, "❌ Использование: /email email@example.com")
    
    elif text.startswith("/nickname"):
        nickname = text.replace("/nickname", "").strip()
        if nickname:
            send_message(chat_id, f"🔍 Поиск никнейма: {nickname}\n⏳ Подождите...")
            result = run_nickname_search(nickname)
            send_message(chat_id, result)
            save_search(chat_id, "nickname", nickname, result)
        else:
            send_message(chat_id, "❌ Использование: /nickname username")
    
    elif text.startswith("/ip"):
        ip = text.replace("/ip", "").strip()
        if ip:
            send_message(chat_id, f"🔍 Поиск IP: {ip}\n⏳ Подождите...")
            result = run_ip_search(ip)
            send_message(chat_id, result)
            save_search(chat_id, "ip", ip, result)
        else:
            send_message(chat_id, "❌ Использование: /ip 8.8.8.8")
    
    elif text.startswith("/phone"):
        phone = text.replace("/phone", "").strip()
        if phone:
            send_message(chat_id, f"🔍 Поиск телефона: {phone}\n⏳ Подождите...")
            result = run_phone_search(phone)
            send_message(chat_id, result)
            save_search(chat_id, "phone", phone, result)
        else:
            send_message(chat_id, "❌ Использование: /phone +380991234567")
    
    elif text.startswith("/car"):
        car = text.replace("/car", "").strip()
        if car:
            send_message(chat_id, f"🔍 Поиск авто: {car}\n⏳ Подождите...")
            result = run_car_search(car)
            send_message(chat_id, result)
            save_search(chat_id, "car", car, result)
        else:
            send_message(chat_id, "❌ Использование: /car а123вв777")
    
    else:
        send_message(chat_id, "❌ Неизвестная команда. Используйте /help")

# ========== ЗАПУСК FLASK ==========
from flask import Flask
import threading

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
            
            if "message" not in update:
                continue
            
            chat_id = update["message"]["chat"]["id"]
            text = update["message"].get("text", "")
            username = update["message"].get("from", {}).get("first_name", "Пользователь")
            
            # Регистрация пользователя
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
