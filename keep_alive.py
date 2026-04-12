import requests
import time

while True:
    try:
        requests.get("https://t.me/TracerGbot")
        print("Пинг отправлен")
    except:
        print("Ошибка")
    time.sleep(300)  # каждые 5 минут
