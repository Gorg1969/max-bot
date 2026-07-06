from flask import Flask, request, jsonify
import logging
import os
import time

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ====== ПРОСТОЙ ДИАГНОСТИЧЕСКИЙ БОТ ======

@app.route('/')
def index():
    """Главная страница — проверка, что бот жив"""
    return """
    <html>
        <head><title>MAX Bot</title></head>
        <body>
            <h1>🤖 MAX Bot is RUNNING!</h1>
            <p>Время: {}</p>
            <p>Статус: ✅ Жив и работает</p>
            <hr>
            <p><b>Тестовые ссылки:</b></p>
            <ul>
                <li><a href="/health">/health</a> — проверка здоровья</li>
                <li><a href="/ping">/ping</a> — просто ping</li>
                <li><a href="/info">/info</a> — информация о сервере</li>
            </ul>
        </body>
    </html>
    """.format(time.strftime('%Y-%m-%d %H:%M:%S'))

@app.route('/health')
def health():
    """Проверка здоровья"""
    return {
        "status": "ok",
        "time": time.strftime('%Y-%m-%d %H:%M:%S'),
        "server": "Render.com"
    }

@app.route('/ping')
def ping():
    """Простой ping"""
    return "pong", 200

@app.route('/info')
def info():
    """Информация о сервере"""
    return {
        "server": "Render.com",
        "status": "running",
        "time": time.strftime('%Y-%m-%d %H:%M:%S'),
        "headers": dict(request.headers)
    }

@app.route('/webhook', methods=['POST'])
def webhook():
    """Тестовый вебхук — просто логирует всё, что пришло"""
    data = request.get_json()
    logger.info("=" * 50)
    logger.info("📩 ПОЛУЧЕН ЗАПРОС НА /webhook")
    logger.info(f"📦 Данные: {data}")
    logger.info("=" * 50)
    return {"ok": True, "received": data}, 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
