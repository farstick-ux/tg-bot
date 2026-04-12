#!/usr/bin/env python
# coding: utf-8

# In[ ]:


import requests
import subprocess
import time
import re

TOKEN = "7632894734:AAGAyaDvdpPgzDgq244Gzj5U4ASms_VQGV0"
URL = f"https://api.telegram.org/bot{TOKEN}/"

def send_message(chat_id, text):
    requests.post(URL + "sendMessage", json={"chat_id": chat_id, "text": text})

def get_updates(offset=None):
    params = {"timeout": 30}
    if offset:
        params["offset"] = offset
    response = requests.get(URL + "getUpdates", params=params)
    return response.json()

def run_email_search(email):
    """Пошук по email через holehe"""
    try:
        result = subprocess.run(["holehe", email], capture_output=True, text=True, timeout=60)
        output = result.stdout
        
        if not output:
            return f"🔍 По email {email} ничего не найдено"
        
        import re
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
    """Швидкий пошук по никнейму"""
    import requests
    
    sites = {
        "GitHub": f"https://github.com/{username}",
        "Twitter": f"https://twitter.com/{username}",
        "Instagram": f"https://instagram.com/{username}",
        "Telegram": f"https://t.me/{username}",
        "Reddit": f"https://reddit.com/user/{username}",
        "YouTube": f"https://youtube.com/@{username}",
        "Twitch": f"https://twitch.tv/{username}",
        "Pinterest": f"https://pinterest.com/{username}",
        "GitLab": f"https://gitlab.com/{username}",
    }
    
    # TikTok перевіряємо окремо (через спеціальний API)
    found = []
    
    # Перевірка TikTok через мобільний API
    try:
        tiktok_url = f"https://www.tiktok.com/@{username}"
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"
        }
        r = requests.get(tiktok_url, headers=headers, timeout=5, allow_redirects=False)
        if r.status_code == 200:
            found.append(f"✅ TikTok: https://tiktok.com/@{username}")
        elif r.status_code == 302:
            # Редирект теж означає що сторінка існує
            found.append(f"✅ TikTok: https://tiktok.com/@{username}")
    except:
        pass
    
    # Інші сайти
    for name, url in sites.items():
        try:
            r = requests.get(url, timeout=5, allow_redirects=False)
            if name == "Telegram":
                r_full = requests.get(url, timeout=5)
                if "tgme_page_title" in r_full.text:
                    found.append(f"✅ {name}: {url}")
            elif r.status_code == 200 or r.status_code == 302:
                found.append(f"✅ {name}: {url}")
        except:
            pass
    
    if found:
        return f"🔍 НИКНЕЙМ: {username}\n\n" + "\n".join(found)
    else:
        return f"🔍 По никнейму {username} ничего не найдено"

def run_phone_search(phone):
    # Убираем лишние символы
    import re
    phone = re.sub(r'[^0-9+]', '', phone)
    
    result = f"НОМЕР: {phone}\n\n"
    
    result += f"WhatsApp: https://wa.me/{phone}\n"
    result += f"Telegram: https://t.me/{phone}\n"
    result += f"Truecaller: https://www.truecaller.com/search/{phone}\n"
    result += f"Google: https://www.google.com/search?q={phone}\n"
    
    # Определение страны по коду
    if phone.startswith('+380'):
        result += f"\nСтрана: Украина\n"
    elif phone.startswith('+7'):
        result += f"\nСтрана: Россия\n"
    elif phone.startswith('+1'):
        result += f"\nСтрана: США/Канада\n"
    elif phone.startswith('+48'):
        result += f"\nСтрана: Польша\n"
    elif phone.startswith('+44'):
        result += f"\nСтрана: Великобритания\n"
    elif phone.startswith('+49'):
        result += f"\nСтрана: Германия\n"
    
    return result

last_id = 0
print("🤖 Бот запущен...")

while True:
    updates = get_updates(last_id + 1)
    
    for update in updates.get("result", []):
        last_id = update["update_id"]
        
        if "message" not in update:
            continue
        
        chat_id = update["message"]["chat"]["id"]
        text = update["message"].get("text", "")
        
        if text == "/start":
            send_message(chat_id, "🤖 OSINT БОТ\n\nКоманды:\n/nickname <ник> - поиск по никнейму\n/email <email> - поиск по email\n/phone <номер> - поиск по телефону\n/help - помощь")
        
        elif text == "/help":
            send_message(chat_id, "📋 ПРИМЕРЫ:\n/nickname qwerty\n/email test@mail.com\n/phone +380991234567")
        
        elif text.startswith("/nickname"):
            username = text.replace("/nickname", "").strip()
            if username:
                send_message(chat_id, f"🔍 Поиск никнейма: {username}\n⏳ Подождите...")
                result = run_nickname_search(username)
                send_message(chat_id, f"📋 РЕЗУЛЬТАТ:\n{result}")
            else:
                send_message(chat_id, "❌ Использование: /nickname никнейм")
        
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


# In[ ]:




