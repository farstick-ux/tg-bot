import requests
import subprocess
import time
import re
import threading
import os
import logging
from typing import Optional, Dict, Any

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ТОКЕН - ОБЯЗАТЕЛЬНО спрячьте!
TOKEN = os.getenv("BOT_TOKEN", "7632894734:AAGAyaDvdpPgzDgq244Gzj5U4ASms_VQGV0")
URL = f"https://api.telegram.org/bot{TOKEN}/"

# ========== KEEP ALIVE ==========
def keep_alive():
    while True:
        time.sleep(300)
        try:
            requests.get("https://tg-bot-f2ww.onrender.com", timeout=10)
            logger.info("Пинг отправлен")
        except Exception as e:
            logger.error(f"Ошибка пинга: {e}")

threading.Thread(target=keep_alive, daemon=True).start()

def send_message(chat_id: int, text: str) -> bool:
    """Отправка сообщения с проверкой ошибок"""
    try:
        # Разбиваем длинные сообщения
        if len(text) > 4000:
            for i in range(0, len(text), 4000):
                response = requests.post(URL + "sendMessage", 
                                        json={"chat_id": chat_id, "text": text[i:i+4000]},
                                        timeout=10)
            return True
        else:
            response = requests.post(URL + "sendMessage", 
                                    json={"chat_id": chat_id, "text": text},
                                    timeout=10)
            return response.status_code == 200
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")
        return False

def get_updates(offset: Optional[int] = None) -> Dict[str, Any]:
    """Получение обновлений с обработкой ошибок"""
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    try:
        response = requests.get(URL + "getUpdates", params=params, timeout=35)
        return response.json()
    except Exception as e:
        logger.error(f"Ошибка получения обновлений: {e}")
        return {"result": []}

def run_photo_search() -> str:
    """Поиск по фото - только ссылки"""
    return """🔎 ПОИСК ПО ФОТО

Для поиска этого фото перейдите по ссылкам:

1. reversely.ai: https://www.reversely.ai/ru/face-search

2. Google Images: https://images.google.com

3. Yandex Images: https://yandex.com/images/

4. TinEye: https://tineye.com

5. Bing Visual Search: https://www.bing.com/visualsearch"""

def run_email_search(email: str) -> str:
    """Поиск по email с использованием holehe"""
    try:
        # Запускаем holehe как subprocess
        result = subprocess.run(
            ["holehe", email, "--no-color"],  # --no-color убирает ANSI коды
            capture_output=True, 
            text=True, 
            timeout=60
        )
        
        output = result.stdout
        error_output = result.stderr
        
        # Если holehe не найден в системе
        if result.returncode == 127:  # command not found
            return f"❌ Holehe не установлен. Установите: pip install holehe"
        
        # Очищаем вывод от ANSI цветов
        clean = re.sub(r'\x1b\[[0-9;]*m', '', output)
        
        # Парсим результаты holehe
        found_sites = []
        for line in clean.split("\n"):
            line = line.strip()
            if "[+]" in line:
                # Извлекаем название сайта
                site = line.replace("[+]", "").strip()
                # Убираем лишние символы
                site = re.sub(r'https?://', '', site)
                site = site.split()[0] if site.split() else site
                if site and len(site) < 100 and site not in found_sites:
                    found_sites.append(f"✅ {site}")
            elif "[×]" in line or "[-]" in line:
                # Не найдено на сайте - пропускаем
                pass
            elif "[?]" in line:
                # Не удалось проверить
                pass
        
        # Формируем результат
        if found_sites:
            result_text = f"🔍 Email: {email}\n\n✅ НАЙДЕНО НА САЙТАХ:\n"
            result_text += "\n".join(found_sites[:30])  # Не более 30 сайтов
            
            # Добавляем ссылки на сервисы
            result_text += f"\n\n🔗 ДОПОЛНИТЕЛЬНО:\n"
            result_text += f"• Have I Been Pwned: https://haveibeenpwned.com/account/{email}\n"
            result_text += f"• DeHashed: https://dehashed.com/search?query={email}\n"
            
            return result_text
        else:
            return f"🔍 Email: {email}\n\n❌ Ничего не найдено через holehe\n\n🔗 Проверьте вручную:\nhttps://haveibeenpwned.com/account/{email}"
            
    except subprocess.TimeoutExpired:
        return f"❌ Таймаут: holehe слишком долго обрабатывает email {email}"
    except FileNotFoundError:
        return "❌ Holehe не установлен в системе. Установите: pip install holehe\nИли выполните: python -m pip install holehe"
    except Exception as e:
        logger.error(f"Ошибка holehe: {e}")
        return f"❌ Ошибка при поиске: {str(e)}"

def run_nickname_search(username: str) -> str:
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
        "Pinterest": f"https://pinterest.com/{username}",
        "VK": f"https://vk.com/{username}"
    }
    
    found = []
    for site_name, url in sites.items():
        try:
            response = requests.get(url, timeout=5, allow_redirects=False)
            if response.status_code == 200:
                # Дополнительная проверка для Telegram
                if site_name == "Telegram":
                    if "tgme_page_title" in response.text and "If you have Telegram" not in response.text:
                        found.append(f"✅ {site_name}: {url}")
                else:
                    found.append(f"✅ {site_name}: {url}")
            elif response.status_code == 302:  # Редирект
                found.append(f"⚠️ {site_name}: {url} (возможно найден)")
        except requests.Timeout:
            continue
        except Exception as e:
            logger.debug(f"Ошибка проверки {site_name}: {e}")
            continue
    
    if found:
        return f"🔍 НИКНЕЙМ: {username}\n\n" + "\n".join(found[:25])
    else:
        return f"🔍 По никнейму {username} ничего не найдено"

def run_ip_search(ip: str) -> str:
    """Поиск по IP"""
    ip_pattern = re.compile(r'^(\d{1,3}\.){3}\d{1,3}$')
    if not ip_pattern.match(ip):
        return "❌ Неверный формат IP-адреса"
    
    try:
        response = requests.get(f"http://ip-api.com/json/{ip}", timeout=10)
        data = response.json()
        
        if data.get('status') == 'success':
            result = f"🌐 IP: {ip}\n\n"
            result += f"📍 Страна: {data.get('country', 'Неизвестно')}\n"
            result += f"🏙️ Город: {data.get('city', 'Неизвестно')}\n"
            result += f"🏢 Провайдер: {data.get('isp', 'Неизвестно')}\n"
            result += f"🗺️ Координаты: {data.get('lat')}, {data.get('lon')}\n"
            result += f"💻 Организация: {data.get('org', 'Неизвестно')}\n"
            return result
        else:
            return f"❌ Не удалось получить информацию об IP {ip}"
    except Exception as e:
        logger.error(f"Ошибка IP поиска: {e}")
        return f"❌ Ошибка: {e}"

def run_phone_search(phone: str) -> str:
    """Поиск по телефону"""
    try:
        import phonenumbers
        from phonenumbers import carrier, geocoder, timezone
        
        phone_clean = re.sub(r'[^0-9+]', '', phone)
        
        result = f"📱 ТЕЛЕФОН: {phone_clean}\n\n"
        
        try:
            number = phonenumbers.parse(phone_clean, None)
            
            if phonenumbers.is_valid_number(number):
                country = geocoder.description_for_number(number, "ru")
                operator = carrier.name_for_number(number, "ru")
                tz = timezone.time_zones_for_number(number)
                
                result += f"✅ Номер валидный\n"
                if country:
                    result += f"📍 Страна: {country}\n"
                if operator:
                    result += f"📡 Оператор: {operator}\n"
                if tz:
                    result += f"🕐 Часовой пояс: {', '.join(tz)}\n"
            else:
                result += "⚠️ Номер невалидный\n"
        except Exception as e:
            result += f"⚠️ Не удалось распознать номер: {e}\n"
        
        result += f"\n🔗 Полезные ссылки:\n"
        result += f"• WhatsApp: https://wa.me/{phone_clean}\n"
        result += f"• Telegram: https://t.me/{phone_clean}\n"
        result += f"• Google: https://www.google.com/search?q={phone_clean}\n"
        
        return result
    except ImportError:
        return "❌ Установите phonenumbers: pip install phonenumbers"
    except Exception as e:
        logger.error(f"Ошибка телефонного поиска: {e}")
        return f"❌ Ошибка: {e}"

# ========== ОСНОВНОЙ ЦИКЛ ==========
def main():
    last_id = 0
    error_count = 0
    logger.info("🤖 Бот запущен...")
    
    while True:
        try:
            updates = get_updates(last_id + 1)
            
            if not updates.get("ok", True) and "result" not in updates:
                error_count += 1
                if error_count > 5:
                    logger.error("Слишком много ошибок, перезапуск...")
                    time.sleep(60)
                    error_count = 0
                continue
            
            error_count = 0
            
            for update in updates.get("result", []):
                last_id = update["update_id"]
                
                if "message" not in update:
                    continue
                
                chat_id = update["message"]["chat"]["id"]
                text = update["message"].get("text", "")
                
                # Обработка команд
                if text == "/start":
                    send_message(chat_id, """🤖 OSINT БОТ

Команды:
/nickname <ник> - поиск по никнейму
/email <email> - поиск по email (holehe)
/phone <номер> - поиск по телефону
/ip <айпи> - поиск по IP
/photo - поиск по фото
/help - помощь""")
                
                elif text == "/help":
                    send_message(chat_id, """📚 ПРИМЕРЫ ИСПОЛЬЗОВАНИЯ:

/nickname qwerty
/email test@mail.com
/phone +380991234567
/ip 8.8.8.8
/photo""")
                
                elif text == "/photo":
                    result = run_photo_search()
                    send_message(chat_id, result)
                
                elif text.startswith("/nickname"):
                    username = text.replace("/nickname", "").strip()
                    if username:
                        send_message(chat_id, f"🔍 Поиск никнейма: {username}\n⏳ Подождите...")
                        result = run_nickname_search(username)
                        send_message(chat_id, f"📊 РЕЗУЛЬТАТ:\n{result}")
                    else:
                        send_message(chat_id, "❌ Использование: /nickname никнейм")
                
                elif text.startswith("/ip"):
                    ip = text.replace("/ip", "").strip()
                    if ip:
                        send_message(chat_id, f"🌐 Поиск IP: {ip}\n⏳ Подождите...")
                        result = run_ip_search(ip)
                        send_message(chat_id, f"📊 РЕЗУЛЬТАТ:\n{result}")
                    else:
                        send_message(chat_id, "❌ Использование: /ip 8.8.8.8")
                
                elif text.startswith("/email"):
                    email = text.replace("/email", "").strip()
                    if email and "@" in email and "." in email:
                        send_message(chat_id, f"📧 Поиск email: {email}\n⏳ Подождите... (до 30 секунд)")
                        result = run_email_search(email)
                        send_message(chat_id, f"📊 РЕЗУЛЬТАТ:\n{result}")
                    else:
                        send_message(chat_id, "❌ Использование: /email email@example.com")
                
                elif text.startswith("/phone"):
                    phone = text.replace("/phone", "").strip()
                    if phone:
                        send_message(chat_id, f"📱 Поиск номера: {phone}\n⏳ Подождите...")
                        result = run_phone_search(phone)
                        send_message(chat_id, f"📊 РЕЗУЛЬТАТ:\n{result}")
                    else:
                        send_message(chat_id, "❌ Использование: /phone +380991234567")
                
                else:
                    if text and not text.startswith("/"):
                        pass
                    elif text:
                        send_message(chat_id, "❌ Неизвестная команда. Используйте /help")
            
            time.sleep(1)
            
        except KeyboardInterrupt:
            logger.info("Бот остановлен пользователем")
            break
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
