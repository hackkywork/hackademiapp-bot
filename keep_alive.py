from flask import Flask
from threading import Thread
import os

app = Flask('')

@app.route('/')
def home():
    # Цей текст бачитиме моніторинг, коли "стукатиме" на сайт
    return "Бот працює! Koyeb, не спи! 🚀"

def run():
    # Koyeb зазвичай передає порт через змінну середовища PORT
    port = int(os.environ.get("PORT", 8000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    # Запускаємо сервер у фоновому потоці, щоб він не блокував бота
    t = Thread(target=run)
    t.start()