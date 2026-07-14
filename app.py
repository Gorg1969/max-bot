from flask import Flask, request, jsonify
import logging
import os

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    """Полный дамп всех данных"""
    logger.info("=" * 60)
    logger.info("📨 ПОЛУЧЕН ВЕБХУК!")
    
    # ВСЕ заголовки
    logger.info("📋 HEADERS:")
    for key, value in request.headers.items():
        logger.info(f"  {key}: {value}")
    
    # ВСЕ данные
    logger.info("📦 RAW DATA:")
    raw_data = request.get_data(as_text=True)
    logger.info(raw_data)
    
    # JSON если есть
    try:
        json_data = request.get_json()
        logger.info("📊 JSON DATA:")
        logger.info(json_data)
    except:
        logger.info("❌ Не JSON")
    
    logger.info("=" * 60)
    
    return jsonify({'status': 'ok'}), 200

@app.route('/')
def index():
    return "Webhook debug server"

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    app.run(host='0.0.0.0', port=port, debug=True)
