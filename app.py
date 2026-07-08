from flask import Flask, request, jsonify
import logging
import os

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    logging.info(f"📩 ВЕБХУК: {data}")
    return jsonify({"ok": True})

@app.route('/')
def index():
    return "✅ Бот работает!"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port)
