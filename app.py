from flask import Flask, request, jsonify, session
import requests
import logging
import os
import urllib3
import json
import tempfile
from modules import Database, FileManager, Publisher, WebInterface, UserAuth, GoogleDrive
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

# ОТКЛЮЧАЕМ ПРЕДУПРЕЖДЕНИЯ SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024 * 2

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== КОНФИГ ==========
TOKEN = os.environ.get("TOKEN") or os.environ.get("MAX_BOT_TOKEN")
BASE_URL = "https://platform-api2.max.ru"
DATA_DIR = "/app/data"

# ========== ЗАГРУЗКА CREDENTIALS ==========
CLIENT_SECRETS_FILE = None

# 1. Пытаемся взять из переменной окружения
creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
if creds_json:
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write(creds_json)
            CLIENT_SECRETS_FILE = f.name
        logger.info("✅ Credentials загружены из переменной окружения")
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки credentials из переменной: {e}")

# 2. Если не получилось — пробуем файл в корне
if not CLIENT_SECRETS_FILE:
    try:
        if os.path.exists("/app/drive_keys.json"):
            CLIENT_SECRETS_FILE = "/app/drive_keys.json"
            logger.info(f"✅ Credentials загружены из файла: {CLIENT_SECRETS_FILE}")
        else:
            logger.error("❌ Не найдены credentials ни в переменной, ни в файле!")
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки credentials из файла: {e}")

# ========== ИНИЦИАЛИЗАЦИЯ МОДУЛЕЙ ==========
db = Database()
fm = FileManager(DATA_DIR)

class APIClient:
    def __init__(self):
        self.token = TOKEN

    def send_message(self, user_id, text):
        try:
            payload = {"text": text, "format": "markdown"}
            response = requests.post(
                f"{BASE_URL}/messages",
                headers={"Authorization": self.token, "Content-Type": "application/json"},
                params={"user_id": user_id},
                json=payload,
                timeout=30,
                verify=False
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
            return False

    def send_message_to_chat(self, chat_id, text):
        try:
            payload = {"text": text, "format": "markdown"}
            response = requests.post(
                f"{BASE_URL}/messages",
                headers={"Authorization": self.token, "Content-Type": "application/json"},
                params={"chat_id": chat_id},
                json=payload,
                timeout=30,
                verify=False
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"❌ Ошибка отправки в чат: {e}")
            return False

api = APIClient()
publisher = Publisher(api, fm, db)
web = WebInterface(fm, publisher)
user_auth = UserAuth(db)

# ========== АВТОРИЗАЦИЯ GOOGLE ==========

@app.route('/auth')
def auth():
    user_id = request.args.get('user_id')
    if not user_id:
        return "❌ Не передан user_id. Используйте: /auth?user_id=ВАШ_ID", 400

    if db.get_user_token(int(user_id)):
        return "✅ Вы уже авторизованы! Вернитесь в бота."

    if not CLIENT_SECRETS_FILE:
        return "❌ Ошибка: не найдены credentials Google. Обратитесь к администратору.", 500

    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=['https://www.googleapis.com/auth/drive.file'],
        redirect_uri='https://maxbot.bothost.tech/oauth2callback'
    )

    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )

    session['state'] = state
    session['user_id'] = user_id

    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
        <h2>🔐 Подключение Google Диска</h2>
        <p>Нажмите кнопку, чтобы разрешить боту доступ к вашему Диску.</p>
        <a href="{authorization_url}" target="_blank">
            <button style="padding: 15px 30px; font-size: 18px; background: #4285F4; color: white; border: none; border-radius: 5px; cursor: pointer;">
                📂 Подключить Google Диск
            </button>
        </a>
        <p style="margin-top: 20px; font-size: 14px; color: #666;">
            После авторизации вернитесь в бота и нажмите "Проверить подключение".
        </p>
    </body>
    </html>
    """

@app.route('/oauth2callback')
def oauth2callback():
    try:
        if request.args.get('state') != session.get('state'):
            return "❌ Ошибка: состояние не совпадает", 400

        code = request.args.get('code')
        user_id = session.get('user_id')

        if not user_id:
            return "❌ Не найден user_id", 400

        if not CLIENT_SECRETS_FILE:
            return "❌ Ошибка: не найдены credentials Google", 500

        flow = Flow.from_client_secrets_file(
            CLIENT_SECRETS_FILE,
            scopes=['https://www.googleapis.com/auth/drive.file'],
            redirect_uri='https://maxbot.bothost.tech/oauth2callback'
        )
        flow.fetch_token(code=code)
        credentials = flow.credentials

        db.save_user_token(
            user_id=int(user_id),
            access_token=credentials.token,
            refresh_token=credentials.refresh_token,
            expires_in=credentials.expiry
        )

        session.clear()

        return """
        <html>
        <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
            <h2>✅ Авторизация прошла успешно!</h2>
            <p>Теперь бот имеет доступ к вашему Google Диску.</p>
            <p>Вернитесь в MAX и отправьте боту команду <strong>/start</strong>.</p>
        </body>
        </html>
        """
    except Exception as e:
        logger.error(f"❌ Ошибка OAuth: {e}")
        return f"❌ Ошибка: {e}", 500

# ========== ПРОВЕРКА АВТОРИЗАЦИИ ==========

@app.route('/check_auth')
def check_auth():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'authorized': False, 'error': 'No user_id'}), 400

    token = user_auth.get_user_token(int(user_id))
    return jsonify({'authorized': token is not None})

# ========== ЗАГРУЗКА НА GOOGLE ДИСК ==========

@app.route('/upload_to_drive', methods=['POST'])
def upload_to_drive():
    try:
        user_id = int(request.form.get('user_id', 151296248))
        logger.info(f"📥 Запрос на загрузку от пользователя {user_id}")
        
        # Проверяем авторизацию
        token = user_auth.get_user_token(user_id)
        if not token:
            logger.warning(f"❌ Пользователь {user_id} не авторизован")
            return jsonify({'success': False, 'message': 'Google Диск не подключён'}), 401
        
        # Проверяем наличие файла
        if 'file' not in request.files:
            logger.warning("❌ Нет файла в запросе")
            return jsonify({'success': False, 'message': 'Файл не выбран'}), 400
        
        file = request.files['file']
        if file.filename == '':
            logger.warning("❌ Пустое имя файла")
            return jsonify({'success': False, 'message': 'Файл не выбран'}), 400
        
        if not file.filename.endswith('.zip'):
            logger.warning(f"❌ Неверный формат файла: {file.filename}")
            return jsonify({'success': False, 'message': 'Файл должен быть в формате .zip'}), 400
        
        logger.info(f"📤 Начинаю загрузку файла {file.filename} на Google Диск")
        
        # Создаём экземпляр GoogleDrive
        drive = GoogleDrive(token)
        
        # Вызываем метод загрузки
        result = web.upload_to_drive(request, user_id, drive)
        
        logger.info(f"✅ Результат загрузки: {result}")
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 500
            
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': f'Ошибка: {str(e)}'}), 500

# ========== ОСТАЛЬНЫЕ МАРШРУТЫ ==========

@app.route('/')
def index():
    return "🤖 MAX Bot is running!"

@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'GET':
        return web.upload_page()

    try:
        user_id = 151296248
        result = web.upload_file(request, user_id)
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 500
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки: {e}")
        return jsonify({'success': False, 'message': f'Ошибка: {str(e)}'}), 500

@app.route('/health')
def health():
    return {"status": "ok"}

@app.route('/setup_webhook')
def setup_webhook():
    token = request.args.get('token') or TOKEN
    if not token:
        return "❌ Токен не найден", 400

    webhook_url = "https://maxbot.bothost.tech/webhook"
    headers = {"Authorization": token, "Content-Type": "application/json"}

    try:
        r = requests.post(
            "https://platform-api2.max.ru/subscriptions",
            headers=headers,
            json={"url": webhook_url},
            timeout=10,
            verify=False
        )
        return f"✅ Вебхук настроен: {r.status_code}"
    except Exception as e:
        return f"❌ Ошибка: {e}"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        logger.info("📩 ПОЛУЧЕН ВЕБХУК!")

        if not data:
            return jsonify({"ok": True}), 200

        user_id = None
        text = None

        if 'message' in data:
            msg = data['message']
            if 'sender' in msg:
                user_id = msg['sender'].get('user_id')
            if 'body' in msg:
                text = msg['body'].get('text')

        if not user_id:
            return jsonify({"ok": True}), 200

        logger.info(f"💬 user_id={user_id}, text={text}")

        if text and text.strip() == '/start':
            api.send_message(
                user_id,
                "🏠 **Главное меню**\n\n"
                "🌐 **Загрузите архив через веб-интерфейс:**\n"
                f"🔗 `https://maxbot.bothost.tech/upload`\n\n"
                "📌 **Требования к архиву:**\n"
                "• Формат: `.zip`\n"
                "• Внутри папки с ID групп: `Название -123456789`\n"
                "• В каждой папке: `info.txt` и изображения\n\n"
                "🔐 [Подключить Google Диск](https://maxbot.bothost.tech/auth?user_id={user_id})\n\n"
                "⏹ Для остановки публикации отправьте `/stop`"
            )
            return jsonify({"ok": True}), 200

        if text and text.strip() == '/stop':
            publisher.stop(user_id)
            api.send_message(user_id, "⏹️ Публикация остановлена.")
            return jsonify({"ok": True}), 200

        if text and 'drive.google.com' in text:
            api.send_message(user_id, "📥 Получил ссылку. Обработка пока не реализована.")
            return jsonify({"ok": True}), 200

        return jsonify({"ok": True}), 200

    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        return jsonify({"ok": False}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port)
