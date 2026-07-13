from flask import Flask, request, jsonify, render_template_string
import requests
import logging
import os
import shutil
import urllib3
import json
import time
from modules import Database, FileManager, Publisher, WebInterface

# ОТКЛЮЧАЕМ ПРЕДУПРЕЖДЕНИЯ SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024 * 2  # 2 ГБ

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== КОНФИГ ==========
TOKEN = os.environ.get("TOKEN") or os.environ.get("MAX_BOT_TOKEN")
BASE_URL = "https://platform-api2.max.ru"
DATA_DIR = "/app/data"

# ========== ИНИЦИАЛИЗАЦИЯ МОДУЛЕЙ ==========
db = Database()
fm = FileManager(DATA_DIR)

class APIClient:
    def __init__(self):
        self.token = TOKEN
        self.base_url = BASE_URL

    def send_message(self, user_id, text, attachments=None):
        """Отправляет сообщение пользователю"""
        try:
            payload = {"text": text, "format": "markdown"}
            if attachments:
                payload["attachments"] = attachments
            response = requests.post(
                f"{self.base_url}/messages",
                headers={"Authorization": self.token, "Content-Type": "application/json"},
                params={"user_id": user_id},
                json=payload,
                timeout=30,
                verify=False
            )
            logger.info(f"📤 Отправка сообщения пользователю {user_id}, статус: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"❌ Ошибка отправки: {response.text}")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
            return False

    def send_message_to_chat(self, chat_id, text):
        """Отправляет сообщение в чат по ID группы (с дефисом)"""
        try:
            payload = {"text": text, "format": "markdown"}
            response = requests.post(
                f"{self.base_url}/messages",
                headers={"Authorization": self.token, "Content-Type": "application/json"},
                params={"chat_id": chat_id},
                json=payload,
                timeout=30,
                verify=False
            )
            logger.info(f"📤 Отправка сообщения в чат {chat_id}, статус: {response.status_code}")
            if response.status_code != 200:
                logger.error(f"❌ Ошибка отправки в чат: {response.text}")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"❌ Ошибка отправки в чат: {e}")
            return False

    def send_photos_to_chat(self, chat_id, photo_files, text=None, caption=None):
        """
        Отправляет фото в чат по одному.
        Сначала загружает фото через /uploads с указанием типа в URL, затем отправляет сообщение.
        """
        try:
            if not photo_files:
                return self.send_message_to_chat(chat_id, text or caption or "")
            
            success = True
            
            for i, (filename, data) in enumerate(photo_files):
                logger.info(f"📤 Загрузка фото {i+1}/{len(photo_files)}: {filename}")
                
                # Пробуем загрузить файл через /uploads с type в URL
                files = {
                    'file': (filename, data, 'image/jpeg')
                }
                
                upload_response = requests.post(
                    f"{self.base_url}/uploads?type=image",
                    headers={"Authorization": self.token},
                    files=files,
                    timeout=30,
                    verify=False
                )
                
                logger.info(f"📤 Загрузка фото {i+1}: статус {upload_response.status_code}")
                
                if upload_response.status_code != 200:
                    logger.error(f"❌ Ошибка загрузки {filename}: {upload_response.status_code}")
                    logger.error(f"Ответ: {upload_response.text[:500]}")
                    success = False
                    break
                
                upload_data = upload_response.json()
                logger.info(f"📤 Ответ загрузки: {upload_data}")
                
                token = upload_data.get('token')
                if not token:
                    logger.error(f"❌ Не удалось получить token для {filename}: {upload_data}")
                    success = False
                    break
                
                logger.info(f"✅ Фото загружено: {filename}, token: {token[:20]}...")
                
                # 2. Отправляем сообщение с фото
                # Для первого фото отправляем с текстом, для остальных - без текста
                payload = {
                    "format": "markdown",
                    "attachments": [
                        {
                            "type": "image",
                            "payload": {"token": token}
                        }
                    ]
                }
                
                if i == 0 and text:
                    payload["text"] = text
                
                response = requests.post(
                    f"{self.base_url}/messages",
                    headers={"Authorization": self.token, "Content-Type": "application/json"},
                    params={"chat_id": chat_id},
                    json=payload,
                    timeout=30,
                    verify=False
                )
                
                logger.info(f"📤 Отправка фото {i+1}/{len(photo_files)} в чат {chat_id}, статус: {response.status_code}")
                
                if response.status_code != 200:
                    logger.error(f"❌ Ошибка отправки фото {i+1}: {response.text[:500]}")
                    success = False
                    break
                else:
                    logger.info(f"✅ Фото {i+1} отправлено успешно")
                
                # Задержка между отправками
                if i < len(photo_files) - 1:
                    time.sleep(1)
            
            return success
            
        except Exception as e:
            logger.error(f"❌ Ошибка отправки фото: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

api = APIClient()
publisher = Publisher(api, fm, db)
web = WebInterface(fm, publisher)

# ========== ХРАНИЛИЩЕ ДЛЯ ВРЕМЕННЫХ ДАННЫХ ПОЛЬЗОВАТЕЛЕЙ ==========
user_temp_data = {}

# ========== HTML СТРАНИЦА ДЛЯ ЗАГРУЗКИ ПАПКИ ==========
UPLOAD_PAGE = """... (оставляем без изменений) ..."""

# ========== ФУНКЦИЯ ДЛЯ ОТПРАВКИ КНОПОК ==========
def send_confirmation_buttons(user_id):
    """Отправляет кнопки подтверждения в MAX"""
    try:
        attachments = [{
            "type": "keyboard",
            "buttons": [
                [
                    {
                        "text": "✅ Да, публиковать",
                        "payload": json.dumps({"action": "confirm_publish", "user_id": user_id})
                    },
                    {
                        "text": "❌ Нет, отменить",
                        "payload": json.dumps({"action": "cancel_publish", "user_id": user_id})
                    }
                ]
            ]
        }]
        
        payload = {
            "text": "Выберите действие:",
            "format": "markdown",
            "attachments": attachments
        }
        
        response = requests.post(
            f"{BASE_URL}/messages",
            headers={"Authorization": TOKEN, "Content-Type": "application/json"},
            params={"user_id": user_id},
            json=payload,
            timeout=30,
            verify=False
        )
        
        if response.status_code == 200:
            logger.info(f"✅ Кнопки отправлены пользователю {user_id}")
            return True
        else:
            logger.error(f"❌ Ошибка отправки кнопок: {response.text}")
            send_text_fallback(user_id)
            return False
            
    except Exception as e:
        logger.error(f"❌ Ошибка отправки кнопок: {e}")
        send_text_fallback(user_id)
        return False

def send_text_fallback(user_id):
    """Отправляет текстовое сообщение вместо кнопок"""
    api.send_message(
        user_id,
        "⚠️ Кнопки временно недоступны. Пожалуйста, напишите:\n"
        "• `Да` - чтобы начать публикацию\n"
        "• `Нет` - чтобы отменить"
    )

# ========== МАРШРУТЫ ==========

@app.route('/')
def index():
    return "🤖 MAX Bot is running!"

@app.route('/upload', methods=['GET'])
def upload_page():
    """Страница загрузки папки"""
    return render_template_string(UPLOAD_PAGE)

@app.route('/upload_folder', methods=['POST'])
def upload_folder():
    """Обработка загрузки папки с поиском info.txt в подпапках"""
    try:
        user_id = int(request.form.get('user_id', 151296248))
        files = request.files.getlist('files[]')
        
        if not files:
            return jsonify({'success': False, 'message': 'Файлы не выбраны'}), 400
        
        logger.info(f"📥 Получено {len(files)} файлов от пользователя {user_id}")
        
        # Получаем папку пользователя
        user_folder = fm.get_user_folder(user_id)
        
        # Очищаем папку пользователя перед загрузкой
        if os.path.exists(user_folder):
            shutil.rmtree(user_folder)
            logger.info(f"🗑️ Папка пользователя {user_id} очищена")
        os.makedirs(user_folder, exist_ok=True)
        
        # Сохраняем файлы с полной структурой
        saved_count = 0
        root_folder_name = None
        
        for file in files:
            # Получаем путь (webkitRelativePath)
            rel_path = file.filename
            if not rel_path:
                rel_path = file.name
            
            # Разбиваем путь на части
            parts = rel_path.split('/')
            
            # Запоминаем имя корневой папки
            if len(parts) >= 1 and not root_folder_name:
                root_folder_name = parts[0]
            
            # Сохраняем файл с полным путём
            full_path = os.path.join(user_folder, rel_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            file.save(full_path)
            saved_count += 1
        
        logger.info(f"✅ Сохранено {saved_count} файлов")
        logger.info(f"📁 Корневая папка: {root_folder_name}")
        
        # Ищем подпапки внутри корневой папки
        valid_folders = []
        invalid_folders = []
        folder_errors = {}
        
        if root_folder_name:
            root_folder_path = os.path.join(user_folder, root_folder_name)
            if os.path.isdir(root_folder_path):
                for item in os.listdir(root_folder_path):
                    item_path = os.path.join(root_folder_path, item)
                    if os.path.isdir(item_path):
                        info_path = os.path.join(item_path, 'info.txt')
                        if os.path.exists(info_path):
                            valid_folders.append(item)
                            logger.info(f"✅ Папка {item} - валидна (есть info.txt)")
                        else:
                            invalid_folders.append(item)
                            folder_errors[item] = "отсутствует info.txt"
                            logger.warning(f"⚠️ В папке {item} нет info.txt")
        
        # Сохраняем результат
        user_temp_data[user_id] = {
            'valid_folders': valid_folders,
            'invalid_folders': invalid_folders,
            'folder_errors': folder_errors
        }
        
        # Формируем сообщение
        message = ""
        if valid_folders:
            message += f"✅ **Найдено {len(valid_folders)} валидных объявлений:**\n"
            for folder in valid_folders:
                message += f"  • {folder}\n"
            message += "\n"
        
        if invalid_folders:
            message += f"❌ **Пропущено {len(invalid_folders)} папок:**\n"
            for folder, error in folder_errors.items():
                message += f"  • {folder} - {error}\n"
        
        # Отправляем результат
        if invalid_folders and valid_folders:
            api.send_message(
                user_id,
                f"📊 **Результат загрузки:**\n\n"
                f"{message}\n"
                f"Публиковать валидные объявления?"
            )
            send_confirmation_buttons(user_id)
            
            return jsonify({
                'success': True,
                'message': 'Загрузка завершена. Проверьте сообщение в боте.',
                'result': {
                    'valid_folders': valid_folders,
                    'invalid_folders': invalid_folders
                }
            })
        elif valid_folders:
            api.send_message(
                user_id,
                f"✅ **Все папки валидны!**\n\n"
                f"Найдено {len(valid_folders)} объявлений:\n"
                f"{', '.join(valid_folders)}\n\n"
                f"🚀 Начинаем публикацию..."
            )
            send_confirmation_buttons(user_id)
            
            return jsonify({
                'success': True,
                'message': f'✅ Загружено {len(valid_folders)} объявлений. Нажмите "Да" для публикации.',
                'result': {
                    'valid_folders': valid_folders,
                    'invalid_folders': invalid_folders
                }
            })
        else:
            api.send_message(
                user_id,
                f"❌ **Нет валидных папок!**\n\n"
                f"{message}\n"
                f"Проверьте структуру папок и попробуйте снова."
            )
            return jsonify({
                'success': False,
                'message': 'Нет валидных папок',
                'result': {'invalid_folders': invalid_folders}
            }), 400
        
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки папки: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        logger.info("📩 ПОЛУЧЕН ВЕБХУК!")

        if not data:
            return jsonify({"ok": True}), 200

        user_id = None
        text = None
        payload = None
        
        if 'message' in data:
            msg = data['message']
            if 'sender' in msg:
                user_id = msg['sender'].get('user_id')
            if 'body' in msg:
                text = msg['body'].get('text')
                payload = msg['body'].get('payload')
                if payload and isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except:
                        pass
        
        if not user_id:
            return jsonify({"ok": True}), 200

        logger.info(f"💬 user_id={user_id}, text={text}, payload={payload}")

        # Обработка кнопок
        if payload and isinstance(payload, dict):
            action = payload.get('action')
            if action == 'confirm_publish':
                api.send_message(user_id, "🚀 Начинаю публикацию валидных объявлений...")
                publisher.start(user_id)
                return jsonify({"ok": True}), 200
            elif action == 'cancel_publish':
                api.send_message(user_id, "⏹️ Публикация отменена. Очищаю данные...")
                fm.clear_user_data(user_id)
                return jsonify({"ok": True}), 200

        # Обработка текстовых команд
        if text:
            text_lower = text.strip().lower()
            if text_lower == 'да' or text_lower == 'yes':
                api.send_message(user_id, "🚀 Начинаю публикацию валидных объявлений...")
                publisher.start(user_id)
                return jsonify({"ok": True}), 200
            elif text_lower == 'нет' or text_lower == 'no':
                api.send_message(user_id, "⏹️ Публикация отменена. Очищаю данные...")
                fm.clear_user_data(user_id)
                return jsonify({"ok": True}), 200

        if text and text.strip() == '/start':
            api.send_message(
                user_id,
                "🏠 **Главное меню**\n\n"
                "🌐 **Загрузите папку с объявлениями через веб-интерфейс:**\n"
                f"🔗 `https://maxbot.bothost.tech/upload`\n\n"
                "📌 **Требования к папке:**\n"
                "• Внутри папки должны быть подпапки с названиями: `Название -123456789`\n"
                "• В каждой подпапке: `info.txt` (текст объявления) и изображения\n"
                "• Можно загружать папку любого размера\n\n"
                "⏹ Для остановки публикации отправьте `/stop`"
            )
            return jsonify({"ok": True}), 200

        if text and text.strip() == '/stop':
            publisher.stop(user_id)
            api.send_message(user_id, "⏹️ Публикация остановлена.")
            return jsonify({"ok": True}), 200

        return jsonify({"ok": True}), 200

    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({"ok": False}), 500

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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port)
