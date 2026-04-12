import requests
import time

while True:
    try:
        requests.get("https://твой-бот.onrender.com")
        print("Пинг отправлен")
    except:
        print("Ошибка")
    time.sleep(300)  # каждые 5 минут
