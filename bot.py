import requests
import subprocess
import time
import re
import threading

TOKEN = "7632894734:AAGAyaDvdpPgzDgq244Gzj5U4ASms_VQGV0"
URL = f"https://api.telegram.org/bot{TOKEN}/"

# ========== KEEP ALIVE ==========
def keep_alive():
    while True:
        time.sleep(300)
        try:
            requests.get("https://tg-bot-f2ww.onrender.com")
            print("Пинг отправлен")
        except:
            pass

threading.Thread(target=keep_alive, daemon=True).start()

# ========== ФУНКЦИИ БОТА ==========
def send_message(chat_id, text):
    requests.post(URL + "sendMessage", json={"chat_id": chat_id, "text": text})

def get_updates(offset=None):
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    response = requests.get(URL + "getUpdates", params=params)
    return response.json()

def run_photo_search():
    result = "🔎 ПОИСК ПО ФОТО\n\n"
    result += "Для поиска этого фото перейдите по ссылкам:\n\n"
    result += "1. reversely.ai:\n" 
    result += "   https://www.reversely.ai/ru/face-search\n\n"
    result += "2. Google Images:\n"
    result += "   https://images.google.com\n\n"
    result += "3. Yandex Images:\n"
    result += "   https://yandex.com/images/\n\n"
    result += "4. TinEye:\n"
    result += "   https://tineye.com\n\n"
    result += "5. Bing Visual Search:\n"
    result += "   https://www.bing.com/visualsearch\n\n"
    result += "КАК ИСПОЛЬЗОВАТЬ:\n"
    result += "1. Сохраните фото\n"
    result += "2. Откройте любой из сервисов выше\n"
    result += "3. Загрузите фото\n"
    result += "4. Посмотрите где оно найдено"
    return result

def run_email_search(email):
    try:
        result = subprocess.run(["holehe", email], capture_output=True, text=True, timeout=60)
        output = result.stdout
        if not output:
            return f"🔍 По email {email} ничего не найдено"
        clean = re.sub(r'\x1b\[[0-9;]*m', '', output)
        found = []
        for line in clean.split("\n"):
            if "[+]" in line:
                site = line.replace("[+]", "").strip()
                if site and "." in site and len(site) < 50:
                    found.append(f"✅ {site}")
        if found:
            return f"🔍 Email: {email}\n\n✅ НАЙДЕНО:\n" + "\n".join(found[:25])
        else:
            return f"🔍 По email {email} ничего не найдено"
    except FileNotFoundError:
        return "❌ Holehe не установлен. Установите: pip install holehe"
    except Exception as e:
        return f"❌ Ошибка: {e}"

def run_nickname_search(username):
    """Автоматическая проверка 10 сайтов"""
    
    sites = {
        "TikTok": f"https://www.tiktok.com/@{username}",
        "Instagram": f"https://instagram.com/{username}",
        "Twitter": f"https://twitter.com/{username}",
        "Telegram": f"https://t.me/{username}",
        "GitHub": f"https://github.com/{username}",
        "YouTube": f"https://youtube.com/@{username}",
        "Twitch": f"https://twitch.tv/{username}",
        "Reddit": f"https://reddit.com/user/{username}",
        "Pinterest": f"https://pinterest.com/{username}",
        "VK": f"https://vk.com/{username}"
    }
    
    found = []
    
    for site_name, url in sites.items():
        try:
            if site_name == "Telegram":
                r = requests.get(url, timeout=5)
                if "tgme_page_title" in r.text and "If you have Telegram" not in r.text:
                    found.append(f"✅ {site_name}: {url}")
            elif site_name == "TikTok":
                r = requests.get(url, timeout=5, allow_redirects=False)
                if r.status_code == 200:
                    r_full = requests.get(url, timeout=5)
                    if "couldn't find" not in r_full.text.lower():
                        found.append(f"✅ {site_name}: {url}")
            else:
                r = requests.get(url, timeout=5, allow_redirects=False)
                if r.status_code == 200:
                    found.append(f"✅ {site_name}: {url}")
        except:
            pass
    
    if found:
        return f"🔍 НИКНЕЙМ: {username}\n\n" + "\n".join(found)
    else:
        return f"🔍 По никнейму {username} ничего не найдено"

def run_ip_search(ip):
    result = f"IP: {ip}\n\n"
    try:
        response = requests.get(f"http://ip-api.com/json/{ip}", timeout=10)
        data = response.json()
        if data.get('status') == 'success':
            result += f"🌎Страна: {data.get('country', 'Неизвестно')}\n"
            result += f"🏙Город: {data.get('city', 'Неизвестно')}\n"
            result += f"📡Провайдер: {data.get('isp', 'Неизвестно')}\n"
            result += f"📍Координаты: {data.get('lat')}, {data.get('lon')}\n"
            result += f"🕘Часовой пояс: {data.get('timezone', 'Неизвестно')}\n"
        else:
            result += "🚫 Ошибка: не удалось получить информацию\n"
    except Exception as e:
        result += f"❌ Ошибка: {e}\n"
    return result

def run_phone_search(phone):
    import re
    import phonenumbers
    from phonenumbers import carrier, geocoder, timezone
    
    phone = re.sub(r'[^0-9+]', '', phone)
    result = f"📞 ТЕЛЕФОН: {phone}\n\n"
    try:
        number = phonenumbers.parse(phone)
        country = geocoder.description_for_number(number, "ru")
        operator = carrier.name_for_number(number, "ru")
        tz = timezone.time_zones_for_number(number)
        result += f"📍 Страна: {country}\n"
        result += f"📡 Оператор: {operator}\n"
        result += f"🕘 Часовой пояс: {tz}\n"
    except:
        pass
    result += f"\n💬 МЕССЕНДЖЕРЫ:\n"
    result += f"WhatsApp: https://wa.me/{phone}\n"
    result += f"Telegram: https://t.me/{phone}\n"
    result += f"\n🔍 ПОИСК:\n"
    result += f"Google: https://www.google.com/search?q={phone}\n"
    result += f"Truecaller: https://www.truecaller.com/search/{phone}\n"
    return result

# ========== ОСНОВНОЙ ЦИКЛ ==========
last_id = 0
print("Бот запущен...")

while True:
    updates = get_updates(last_id + 1)
    
    for update in updates.get("result", []):
        last_id = update["update_id"]
        if "message" not in update:
            continue
        
        chat_id = update["message"]["chat"]["id"]
        text = update["message"].get("text", "")
        
        if text == "/start":
            send_message(chat_id, "🤖OSINT БОТ\n\nКоманды:\n/nickname <ник> - поиск по никнейму\n/email <email> - поиск по email\n/phone <номер> - поиск по телефону\n/ip <айпи> - поиск по айпи\n/photo - поиск по фото\n/help - помощь")
        
        elif text == "/help":
            send_message(chat_id, "📋ПРИМЕРЫ:\n/nickname qwerty\n/email test@mail.com\n/phone +380991234567\n/ip 8.8.8.8")
        
        elif text == "/photo":
            result = run_photo_search()
            send_message(chat_id, result)
        
        elif text.startswith("/nickname"):
            username = text.replace("/nickname", "").strip()
            if username:
                send_message(chat_id, f"🔎 Поиск никнейма: {username}\n⏳ Подождите...")
                result = run_nickname_search(username)
                send_message(chat_id, f"📋 РЕЗУЛЬТАТ:\n{result}")
            else:
                send_message(chat_id, "❌ Использование: /nickname никнейм")
        
        elif text.startswith("/ip"):
            ip = text.replace("/ip", "").strip()
            if ip:
                send_message(chat_id, f"🔎 Поиск IP: {ip}\n⏳ Подождите...")
                result = run_ip_search(ip)
                send_message(chat_id, f"📋 РЕЗУЛЬТАТ:\n{result}")
            else:
                send_message(chat_id, "❌ Использование: /ip 8.8.8.8")
        
        elif text.startswith("/email"):
            email = text.replace("/email", "").strip()
            if email and "@" in email:
                send_message(chat_id, f"🔍 Поиск email: {email}\n⏳ Подождите...")
                result = run_email_search(email)
                send_message(chat_id, f"📋 РЕЗУЛЬТАТ:\n{result}")
            else:
                send_message(chat_id, "❌ Использование: /email email@example.com")
        
        elif text.startswith("/phone"):
            phone = text.replace("/phone", "").strip()
            if phone:
                send_message(chat_id, f"🔍 Поиск номера: {phone}\n⏳ Подождите...")
                result = run_phone_search(phone)
                send_message(chat_id, f"📋 РЕЗУЛЬТАТ:\n{result}")
            else:
                send_message(chat_id, "❌ Использование: /phone +380991234567")
    
    time.sleep(1)
