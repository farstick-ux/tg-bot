import requests
import subprocess
import time
import re
import threading
import os
import logging
from typing import Optional, Dict, Any
from flask import Flask, request, jsonify

# ========== НАСТРОЙКА ==========
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ТОКЕН - используйте переменные окружения!
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    logger.error("BOT_TOKEN не установлен!")
    # Для тестов - НЕ ИСПОЛЬЗУЙТЕ В ПРОДАКШЕНЕ!
    TOKEN = "7632894734:AAGAyaDvdpPgzDgq244Gzj5U4ASms_VQGV0"

URL = f"https://api.telegram.org/bot{TOKEN}/"

# ========== FLASK ДЛЯ HEALTH CHECK ==========
flask_app = Flask(__name__)

@flask_app.route('/')
def health_check():
    return jsonify({"status": "ok", "message": "Bot is running"}), 200

@flask_app.route('/health')
def health():
    return jsonify({"status": "alive", "timestamp": time.time()}), 200

def run_flask():
    """Запускаем Flask на порту, который требует Render"""
    port = int(os.getenv("PORT", 10000))
    logger.info(f"Запуск Flask сервера на порту {port}")
    flask_app.run(host='0.0.0.0', port=port)

# Запускаем Flask в отдельном потоке
flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()

# ========== KEEP ALIVE (уже не нужен, но оставлю) ==========
def keep_alive():
    while True:
        time.sleep(300)
        try:
            # Пингуем себя через internal URL
            requests.get("http://localhost:10000/health", timeout=5)
            logger.info("Health check успешен")
        except Exception as e:
            logger.debug(f"Health check: {e}")

threading.Thread(target=keep_alive, daemon=True).start()

# ========== ФУНКЦИИ БОТА ==========
def send_message(chat_id: int, text: str) -> bool:
    try:
        response = requests.post(URL + "sendMessage", 
                                json={"chat_id": chat_id, "text": text},
                                timeout=10)
        return response.status_code == 200
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")
        return False

def get_updates(offset: Optional[int] = None) -> Dict[str, Any]:
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    try:
        response = requests.get(URL + "getUpdates", params=params, timeout=35)
        return response.json()
    except Exception as e:
        logger.error(f"Ошибка получения обновлений: {e}")
        return {"result": []}

def run_email_search(email: str) -> str:
    """Поиск по email с использованием holehe (исправленная версия)"""
    try:
        result = subprocess.run(
            ["holehe", email, "--no-color"],
            capture_output=True, 
            text=True, 
            timeout=60
        )
        
        if result.returncode == 127:
            return f"❌ Holehe не установлен. Установите: pip install holehe"
        
        # Очищаем от ANSI кодов
        clean = re.sub(r'\x1b\[[0-9;]*m', '', result.stdout)
        
        found_sites = []
        excluded_keywords = ['email', 'e-mail', 'mail', 'found', 'site', 'service', 'web']
        
        for line in clean.split("\n"):
            line = line.strip()
            if "[+]" in line:
                # Извлекаем название сайта
                site = line.replace("[+]", "").strip()
                
                # Убираем URL протоколы
                site = re.sub(r'https?://', '', site)
                
                # Берем первое слово или домен
                parts = site.split()
                if parts:
                    site = parts[0]
                
                # Очищаем от лишних символов
                site = site.strip('.,;:!?')
                
                # Фильтруем мусорные названия
                is_valid = True
                site_lower = site.lower()
                
                # Проверка на мусорные слова
                for bad_word in excluded_keywords:
                    if bad_word in site_lower and len(site) < 10:
                        is_valid = False
                        break
                
                # Проверка, что это похоже на домен или название сайта
                if is_valid and len(site) > 2 and not site.isdigit():
                    # Убираем дубликаты
                    if site not in found_sites:
                        found_sites.append(f"✅ {site}")
        
        # Дополнительная фильтрация результата
        filtered_sites = []
        for item in found_sites:
            # Убираем совсем короткие или бессмысленные
            site_name = item.replace("✅ ", "")
            if len(site_name) > 2 and site_name.lower() not in ['email', 'mail', 'web', 'site']:
                filtered_sites.append(item)
        
        if filtered_sites:
            result_text = f"🔍 Email: {email}\n\n✅ НАЙДЕНО НА САЙТАХ:\n"
            result_text += "\n".join(filtered_sites[:30])
            result_text += f"\n\n🔗 Проверить вручную:\nhttps://haveibeenpwned.com/account/{email}"
            return result_text
        else:
            return f"🔍 Email: {email}\n\n❌ Ничего не найдено через holehe\n\n🔗 Проверить вручную:\nhttps://haveibeenpwned.com/account/{email}"
            
    except subprocess.TimeoutExpired:
        return f"❌ Таймаут: holehe слишком долго обрабатывает email {email}"
    except FileNotFoundError:
        return "❌ Holehe не установлен. Установите: pip install holehe"
    except Exception as e:
        logger.error(f"Ошибка holehe: {e}")
        return f"❌ Ошибка при поиске: {str(e)}"

def run_nickname_search(username: str) -> str:
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
    else:
        return f"🔍 По никнейму {username} ничего не найдено"

def run_ip_search(ip: str) -> str:
    try:
        response = requests.get(f"http://ip-api.com/json/{ip}", timeout=10)
        data = response.json()
        if data.get('status') == 'success':
            result = f"🌐 IP: {ip}\n\n"
            result += f"📍 Страна: {data.get('country', 'Неизвестно')}\n"
            result += f"🏙️ Город: {data.get('city', 'Неизвестно')}\n"
            result += f"🏢 Провайдер: {data.get('isp', 'Неизвестно')}\n"
            return result
        else:
            return f"❌ Не удалось найти IP {ip}"
    except Exception as e:
        return f"❌ Ошибка: {e}"

def run_phone_search(phone: str) -> str:
    phone_clean = re.sub(r'[^0-9+]', '', phone)
    result = f"📱 ТЕЛЕФОН: {phone_clean}\n\n"
    result += f"• WhatsApp: https://wa.me/{phone_clean}\n"
    result += f"• Telegram: https://t.me/{phone_clean}\n"
    result += f"• Google: https://www.google.com/search?q={phone_clean}\n"
    return result

def run_photo_search() -> str:
    return """🔎 ПОИСК ПО ФОТО

Ссылки для поиска:
1. https://www.reversely.ai/ru/face-search
2. https://images.google.com
3. https://yandex.com/images/
4. https://tineye.com
5. https://www.bing.com/visualsearch"""

# ========== ОСНОВНОЙ ЦИКЛ БОТА ==========
def main():
    last_id = 0
    logger.info("🤖 Бот запущен и готов к работе!")
    
    while True:
        try:
            updates = get_updates(last_id + 1)
            
            for update in updates.get("result", []):
                last_id = update["update_id"]
                
                if "message" not in update:
                    continue
                
                chat_id = update["message"]["chat"]["id"]
                text = update["message"].get("text", "")
                
                if text == "/start":
                    send_message(chat_id, """🤖 OSINT БОТ

Команды:
/nickname <ник> - поиск по никнейму
/email <email> - поиск по email
/phone <номер> - поиск по телефону
/ip <айпи> - поиск по IP
/photo - поиск по фото
/help - помощь""")
                
                elif text == "/help":
                    send_message(chat_id, "📚 Примеры:\n/nickname qwerty\n/email test@mail.com\n/phone +380991234567\n/ip 8.8.8.8")
                
                elif text == "/photo":
                    send_message(chat_id, run_photo_search())
                
                elif text.startswith("/nickname"):
                    username = text.replace("/nickname", "").strip()
                    if username:
                        send_message(chat_id, f"🔍 Поиск {username}...")
                        result = run_nickname_search(username)
                        send_message(chat_id, result)
                    else:
                        send_message(chat_id, "❌ Использование: /nickname никнейм")
                
                elif text.startswith("/ip"):
                    ip = text.replace("/ip", "").strip()
                    if ip:
                        send_message(chat_id, run_ip_search(ip))
                    else:
                        send_message(chat_id, "❌ Использование: /ip 8.8.8.8")
                
                elif text.startswith("/email"):
                    email = text.replace("/email", "").strip()
                    if email and "@" in email:
                        send_message(chat_id, f"📧 Поиск {email}... (до 30 сек)")
                        result = run_email_search(email)
                        send_message(chat_id, result)
                    else:
                        send_message(chat_id, "❌ Использование: /email email@example.com")
                
                elif text.startswith("/phone"):
                    phone = text.replace("/phone", "").strip()
                    if phone:
                        send_message(chat_id, run_phone_search(phone))
                    else:
                        send_message(chat_id, "❌ Использование: /phone +380991234567")
            
            time.sleep(1)
            
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")
            time.sleep(10)

if __name__ == "__main__":
    # Небольшая задержка для запуска Flask
    time.sleep(2)
    main()
