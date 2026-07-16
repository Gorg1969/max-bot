# app.py - исправленная версия с обработкой типов
from flask import Flask, request, jsonify, render_template_string, send_file
import requests
import logging
import os
import shutil
import urllib3
import json
import threading
import time
import queue
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
from werkzeug.exceptions import ClientDisconnected

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024

# НАСТРОЙКА ЛОГИРОВАНИЯ
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("MAX_TOKEN") or os.environ.get("MAX_BOT_TOKEN") or os.environ.get("TOKEN")
BASE_URL = "https://platform-api2.max.ru"
DATA_DIR = "/app/data"

if not TOKEN:
    logger.error("❌ ТОКЕН НЕ НАЙДЕН!")

# Импортируем модули
try:
    from modules import Database, FileManager, Publisher, WebInterface
    from modules.report_generator import ReportGenerator
    
    db = Database()
    fm = FileManager(DATA_DIR)
    logger.info("✅ Модули импортированы успешно")
except Exception as e:
    logger.error(f"❌ Ошибка импорта модулей: {e}")
    import traceback
    traceback.print_exc()
    raise

# ========== УТИЛИТКА ДЛЯ ОТЛАДКИ ==========
class DebugAPIClient:
    def __init__(self):
        self.token = TOKEN
        self.base_url = BASE_URL
        self.debug_dir = "/app/debug_logs"
        os.makedirs(self.debug_dir, exist_ok=True)
        logger.info(f"✅ DebugAPIClient инициализирован")
        
    def _log_request(self, method: str, url: str, headers: dict, data: dict, response: requests.Response):
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
            log_file = os.path.join(self.debug_dir, f"request_{timestamp}.log")
            
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write("=" * 80 + "\n")
                f.write(f"TIMESTAMP: {datetime.now().isoformat()}\n")
                f.write(f"METHOD: {method}\n")
                f.write(f"URL: {url}\n")
                f.write("-" * 40 + "\n")
                f.write("HEADERS:\n")
                for key, value in headers.items():
                    if key.lower() == 'authorization':
                        value = value[:15] + "..." if value else ""
                    f.write(f"  {key}: {value}\n")
                f.write("-" * 40 + "\n")
                f.write("REQUEST DATA:\n")
                try:
                    f.write(json.dumps(data, indent=2, ensure_ascii=False) if data else "None\n")
                except:
                    f.write(str(data) if data else "None\n")
                f.write("-" * 40 + "\n")
                f.write("RESPONSE:\n")
                f.write(f"STATUS: {response.status_code}\n")
                f.write(f"HEADERS:\n")
                for key, value in response.headers.items():
                    f.write(f"  {key}: {value}\n")
                f.write("-" * 40 + "\n")
                f.write("BODY (first 2000 chars):\n")
                body = response.text[:2000] if response.text else "Empty"
                f.write(body)
                if response.text and len(response.text) > 2000:
                    f.write(f"\n... (truncated, total {len(response.text)} chars)")
                f.write("\n" + "=" * 80 + "\n")
                
            logger.info(f"📝 Лог запроса сохранен: {log_file}")
            return log_file
            
        except Exception as e:
            logger.error(f"❌ Ошибка логирования: {e}")
            return None
    
    def send_message(self, user_id, text, attachments=None):
        if not self.token:
            return False
        
        try:
            payload = {"text": text, "format": "markdown"}
            if attachments:
                payload["attachments"] = attachments
            
            url = f"{self.base_url}/messages"
            headers = {
                "Authorization": self.token,
                "Content-Type": "application/json"
            }
            params = {"user_id": user_id}
            
            logger.info(f"📤 [API] Отправка сообщения пользователю {user_id}")
            
            response = requests.post(
                url,
                headers=headers,
                params=params,
                json=payload,
                timeout=30,
                verify=False
            )
            
            self._log_request("POST", url, headers, {"params": params, "payload": payload}, response)
            
            if response.status_code == 200:
                logger.info(f"✅ Сообщение отправлено пользователю {user_id}")
                return True
            else:
                logger.error(f"❌ Ошибка отправки пользователю {user_id}: {response.status_code}")
                return False
            
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
            return False
    
    def upload_file(self, image_data) -> Optional[str]:
        """Загружает файл с логированием"""
        if not self.token:
            logger.error("❌ [UPLOAD] Токен не установлен")
            return None
        
        try:
            # 1. Получаем URL для загрузки
            url = f"{self.base_url}/uploads"
            headers = {"Authorization": self.token}
            params = {"type": "image"}
            
            logger.info(f"📤 [UPLOAD] Запрос URL для загрузки")
            
            response = requests.post(
                url,
                headers=headers,
                params=params,
                timeout=30,
                verify=False
            )
            
            self._log_request("POST", url, headers, {"params": params}, response)
            
            if response.status_code != 200:
                logger.error(f"❌ [UPLOAD] Ошибка получения URL: {response.status_code}")
                logger.error(f"  Response: {response.text[:500]}")
                return None
            
            try:
                upload_data = response.json()
            except Exception as e:
                logger.error(f"❌ [UPLOAD] Не удалось распарсить JSON: {e}")
                logger.error(f"  Response: {response.text[:500]}")
                return None
            
            upload_url = upload_data.get('url')
            if not upload_url:
                logger.error(f"❌ [UPLOAD] Не получен URL: {upload_data}")
                return None
            
            logger.info(f"✅ [UPLOAD] Получен URL для загрузки")
            
            # 2. Извлекаем байты изображения
            if isinstance(image_data, dict):
                if 'data' in image_data:
                    img_data = image_data['data']
                else:
                    for key, value in image_data.items():
                        if isinstance(value, (list, bytes, bytearray)):
                            img_data = value
                            break
                    else:
                        logger.error(f"❌ [UPLOAD] В словаре нет данных: {image_data.keys()}")
                        return None
            else:
                img_data = image_data
            
            if isinstance(img_data, list):
                image_bytes = bytes(img_data)
            elif isinstance(img_data, (bytes, bytearray)):
                image_bytes = bytes(img_data)
            else:
                logger.error(f"❌ [UPLOAD] Неподдерживаемый тип данных: {type(img_data)}")
                return None
            
            logger.info(f"📸 [UPLOAD] Размер изображения: {len(image_bytes)} байт")
            
            # 3. Отправляем файл
            files = {'data': ('image.jpg', image_bytes, 'image/jpeg')}
            
            logger.info(f"📤 [UPLOAD] Отправка файла")
            
            upload_response = requests.post(
                upload_url,
                files=files,
                timeout=60,
                verify=False
            )
            
            self._log_request("POST", upload_url, {}, {"files": "binary data"}, upload_response)
            
            if upload_response.status_code != 200:
                logger.error(f"❌ [UPLOAD] Ошибка загрузки: {upload_response.status_code}")
                logger.error(f"  Response: {upload_response.text[:500]}")
                return None
            
            try:
                upload_result = upload_response.json()
            except Exception as e:
                logger.error(f"❌ [UPLOAD] Не удалось распарсить JSON ответа: {e}")
                logger.error(f"  Response: {upload_response.text[:500]}")
                return None
            
            # 4. Извлекаем токен
            token = None
            if 'photos' in upload_result and isinstance(upload_result['photos'], dict):
                for photo_key, photo_data in upload_result['photos'].items():
                    if isinstance(photo_data, dict) and 'token' in photo_data:
                        token = photo_data['token']
                        logger.info(f"  Найден токен в photos[{photo_key}]")
                        break
            
            if not token and 'token' in upload_result:
                token = upload_result['token']
                logger.info(f"  Найден токен в корне")
            
            if token:
                logger.info(f"✅ [UPLOAD] Файл загружен успешно, токен: {token[:20]}...")
                return token
            else:
                logger.error(f"❌ [UPLOAD] Не получен токен: {upload_result}")
                return None
                
        except Exception as e:
            logger.error(f"❌ [UPLOAD] Ошибка: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def send_to_chat(self, chat_id: str, text: str, image_tokens: List[str]) -> bool:
        """Отправляет сообщение в чат с логированием"""
        if not self.token:
            return False
        
        try:
            attachments = []
            for token in image_tokens[:10]:
                attachments.append({
                    "type": "image",
                    "payload": {"token": token}
                })
            
            payload = {
                "text": text,
                "format": "markdown"
            }
            
            if attachments:
                payload["attachments"] = attachments
            
            chat_id_with_dash = f"-{chat_id}" if not str(chat_id).startswith('-') else chat_id
            
            url = f"{self.base_url}/messages"
            headers = {
                "Authorization": self.token,
                "Content-Type": "application/json"
            }
            params = {"chat_id": chat_id_with_dash}
            
            logger.info(f"📤 [API] Отправка в чат {chat_id_with_dash} с {len(attachments)} фото")
            
            response = requests.post(
                url,
                headers=headers,
                params=params,
                json=payload,
                timeout=60,
                verify=False
            )
            
            self._log_request("POST", url, headers, {"params": params, "payload": payload}, response)
            
            if response.status_code == 200:
                logger.info(f"✅ Сообщение отправлено в чат {chat_id_with_dash}")
                return True
            else:
                logger.error(f"❌ Ошибка: {response.status_code} - {response.text[:200]}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
            return False

# Создаем экземпляры
api = DebugAPIClient()
publisher = Publisher(api, fm, db)
report_gen = ReportGenerator(fm, db)

# ========== HTML СТРАНИЦА (сокращенная версия для экономии места) ==========
# Полный HTML код здесь (из предыдущего ответа)
# ...

# ========== МАРШРУТЫ ==========

@app.route('/')
def index():
    return "🤖 MAX Bot is running!"

@app.route('/upload', methods=['GET'])
def upload_page():
    return render_template_string(UPLOAD_PAGE)

@app.route('/download_logs', methods=['GET'])
def download_logs():
    try:
        import zipfile
        from io import BytesIO
        
        debug_dir = "/app/debug_logs"
        if not os.path.exists(debug_dir):
            return "❌ Нет логов для скачивания", 404
        
        memory_file = BytesIO()
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            for filename in os.listdir(debug_dir):
                filepath = os.path.join(debug_dir, filename)
                if os.path.isfile(filepath):
                    zf.write(filepath, filename)
        
        memory_file.seek(0)
        return send_file(
            memory_file,
            as_attachment=True,
            download_name=f"api_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
            mimetype='application/zip'
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка скачивания логов: {e}")
        return str(e), 500

@app.route('/publish_folder', methods=['POST'])
def publish_folder():
    try:
        # Получаем данные
        data = request.get_json()
        if not data:
            logger.error("❌ Нет данных в запросе")
            return jsonify({'success': False, 'message': 'Нет данных'}), 400
        
        logger.info(f"📥 Получены данные: {json.dumps(data, ensure_ascii=False)[:500]}")
        
        # Извлекаем user_id
        user_id = data.get('user_id')
        if not user_id:
            logger.error("❌ Нет user_id")
            return jsonify({'success': False, 'message': 'Нет user_id'}), 400
        
        # Извлекаем folder
        folder_data = data.get('folder')
        if not folder_data:
            logger.error("❌ Нет folder_data")
            return jsonify({'success': False, 'message': 'Нет данных папки'}), 400
        
        # Извлекаем max_photos с обработкой разных типов
        max_photos_raw = data.get('max_photos', 6)
        
        # ПРАВИЛЬНАЯ ОБРАБОТКА ТИПА max_photos
        if isinstance(max_photos_raw, dict):
            # Если это словарь, пытаемся извлечь значение
            max_photos = max_photos_raw.get('value', 6)
            if isinstance(max_photos, dict):
                max_photos = 6
        elif isinstance(max_photos_raw, (int, float)):
            max_photos = int(max_photos_raw)
        elif isinstance(max_photos_raw, str):
            try:
                max_photos = int(max_photos_raw)
            except:
                max_photos = 6
        else:
            max_photos = 6
        
        # Ограничиваем
        max_photos = max(1, min(max_photos, 10))
        
        # Извлекаем данные папки
        folder_name = folder_data.get('folderName')
        ad_text = folder_data.get('adText')
        metadata_text = folder_data.get('metadataText')
        images = folder_data.get('images', [])
        
        # Ограничиваем количество фото
        if isinstance(images, list) and len(images) > max_photos:
            images = images[:max_photos]
        
        logger.info(f"📦 Получена папка: {folder_name} от пользователя {user_id}")
        logger.info(f"📝 Текст: {len(ad_text) if ad_text else 0} символов")
        logger.info(f"🖼️ Фото: {len(images) if isinstance(images, list) else 0} (макс: {max_photos})")
        
        if not TOKEN:
            return jsonify({'success': False, 'message': 'Токен не настроен'}), 500
        
        success, message = publisher.publish_single_folder(
            user_id, folder_name, ad_text, metadata_text, images
        )
        
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'message': message}), 500
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/stop_publish', methods=['POST'])
def stop_publish():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'message': 'Нет user_id'}), 400
        
        publisher.stop(user_id)
        logger.info(f"⏹️ Остановка публикации для пользователя {user_id}")
        return jsonify({'success': True, 'message': 'Публикация остановлена'})
        
    except Exception as e:
        logger.error(f"❌ Ошибка остановки: {e}")
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
                "🌐 **Загрузить папку:**\n"
                f"🔗 https://maxbot.bothost.tech/upload?user_id={user_id}\n\n"
                "📊 **Получить отчет:**\n"
                f"🔗 https://maxbot.bothost.tech/report/{user_id}\n\n"
                "⏹ **Остановить публикацию:** `/stop`\n\n"
                "📋 **Инструкция:**\n"
                "1. Подготовьте папки с объявлениями\n"
                "2. Используйте разделитель #изъятая\n"
                "3. Фото до 10 шт на объявление\n\n"
                "⚙️ **Настройки в веб-интерфейсе:**\n"
                "• Максимум фото: 1-10\n"
                "• Задержка между папками\n"
                "• Режим очереди: последовательный/параллельный"
            )
            return jsonify({"ok": True}), 200
        
        if text and text.strip() == '/stop':
            publisher.stop(user_id)
            api.send_message(user_id, "⏹️ **Публикация остановлена!**\n\n✅ Все процессы остановлены")
            return jsonify({"ok": True}), 200
        
        if text and text.strip() == '/report':
            api.send_message(user_id, "📊 Создаю отчет...")
            report_path = report_gen.generate_report(user_id)
            if report_path:
                filename = os.path.basename(report_path)
                download_url = f"https://maxbot.bothost.tech/download_report/{user_id}/{filename}"
                api.send_message(
                    user_id,
                    f"📊 **Отчет создан!**\n\n"
                    f"🔗 [Скачать отчет]({download_url})"
                )
            else:
                api.send_message(user_id, "❌ Нет данных для отчета.")
            return jsonify({"ok": True}), 200
        
        return jsonify({"ok": True}), 200
    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        return jsonify({"ok": False}), 500

@app.route('/report/<int:user_id>')
def report_page(user_id):
    report_path = report_gen.generate_report(user_id)
    if not report_path:
        return "❌ Нет данных для отчета", 404
    
    filename = os.path.basename(report_path)
    download_url = f"/download_report/{user_id}/{filename}"
    
    return f"""
    <html>
    <head><title>Отчет</title></head>
    <body style="font-family: Arial; max-width: 600px; margin: 50px auto; text-align: center;">
        <h1>📊 Отчет готов!</h1>
        <p><a href="{download_url}" style="display: inline-block; padding: 12px 30px; background: #28a745; color: white; text-decoration: none; border-radius: 5px;">📥 Скачать отчет</a></p>
        <p><a href="/upload">⬅️ Вернуться к загрузке</a></p>
    </body>
    </html>
    """

@app.route('/download_report/<int:user_id>/<path:filename>')
def download_report(user_id, filename):
    try:
        user_folder = fm.get_user_folder(user_id)
        file_path = os.path.join(user_folder, filename)
        
        if not os.path.exists(file_path):
            return "❌ Файл не найден", 404
        
        response = send_file(file_path, as_attachment=True, download_name=filename)
        return response
        
    except Exception as e:
        logger.error(f"❌ Ошибка скачивания: {e}")
        return str(e), 500

@app.route('/health')
def health():
    return {"status": "ok"}

@app.route('/status')
def status():
    return {"status": "running", "token_set": bool(TOKEN)}

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
            json={"url": webhook_url, "update_types": ["message_created", "bot_started", "bot_stopped"]},
            timeout=10,
            verify=False
        )
        if r.status_code == 200:
            return f"✅ Вебхук настроен: {webhook_url}"
        else:
            return f"❌ Ошибка: {r.status_code} - {r.text}"
    except Exception as e:
        return f"❌ Ошибка: {e}"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    if TOKEN:
        logger.info(f"✅ Токен найден (первые 10): {TOKEN[:10]}...")
    app.run(host='0.0.0.0', port=port, threaded=True)
