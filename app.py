from flask import Flask, request, jsonify, render_template_string, send_from_directory
import requests
import logging
import os
import shutil
import urllib3
import zipfile
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

    def send_message_to_chat_with_attachments(self, chat_id, text, attachments):
        try:
            payload = {
                "text": text,
                "format": "markdown",
                "attachments": attachments
            }
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
            logger.error(f"❌ Ошибка отправки с вложениями: {e}")
            return False

api = APIClient()
publisher = Publisher(api, fm, db)

# ========== HTML СТРАНИЦА ДЛЯ ЗАГРУЗКИ ==========
UPLOAD_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Загрузка объявлений</title>
    <style>
        body { font-family: Arial; max-width: 800px; margin: 50px auto; padding: 20px; }
        .container { border: 2px dashed #ccc; padding: 40px; text-align: center; border-radius: 10px; }
        .drop-zone { border: 2px dashed #007bff; padding: 40px; margin: 20px 0; border-radius: 10px; background: #f8f9fa; }
        .drop-zone.dragover { background: #e3f2fd; border-color: #0056b3; }
        input[type="file"] { display: none; }
        .btn { background: #007bff; color: white; padding: 12px 30px; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; }
        .btn:hover { background: #0056b3; }
        .status { margin-top: 20px; padding: 15px; border-radius: 5px; display: none; }
        .status.success { background: #d4edda; color: #155724; display: block; }
        .status.error { background: #f8d7da; color: #721c24; display: block; }
        .status.info { background: #d1ecf1; color: #0c5460; display: block; }
        .file-list { text-align: left; margin: 20px 0; padding: 0; list-style: none; }
        .file-list li { background: #f8f9fa; padding: 10px; margin: 5px 0; border-radius: 5px; border-left: 3px solid #007bff; }
        .progress-bar { width: 100%; height: 20px; background: #e9ecef; border-radius: 10px; overflow: hidden; margin: 10px 0; display: none; }
        .progress-bar .progress { height: 100%; background: #28a745; transition: width 0.3s; width: 0%; }
        #log { background: #1e1e1e; color: #d4d4d4; padding: 15px; border-radius: 5px; font-family: monospace; font-size: 12px; max-height: 300px; overflow-y: auto; margin: 20px 0; display: none; white-space: pre-wrap; }
        .instructions {
            background: #fff3cd;
            padding: 15px;
            border-radius: 5px;
            margin: 20px 0;
            text-align: left;
            border-left: 4px solid #ffc107;
        }
        .instructions code {
            background: #f8f9fa;
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 14px;
        }
    </style>
</head>
<body>
    <h1>📤 Загрузка объявлений</h1>
    
    <div class="instructions">
        <strong>📌 Инструкция:</strong><br>
        1. Подготовьте папку с объявлениями<br>
        2. Внутри папки должны быть подпапки с названиями типа: <code>Название -123456789</code><br>
        3. В каждой подпапке: <code>info.txt</code> (текст объявления) и изображения<br>
        4. Выберите папку и нажмите "Загрузить"
    </div>
    
    <div class="container">
        <div class="drop-zone" id="dropZone">
            <p>📂 Перетащите папку сюда</p>
            <p>или</p>
            <button class="btn" onclick="document.getElementById('folderInput').click()">Выбрать папку</button>
            <input type="file" id="folderInput" webkitdirectory multiple>
        </div>
        
        <div id="fileList" style="display:none;">
            <h4>📄 Выбранные файлы:</h4>
            <ul class="file-list" id="fileListContent"></ul>
            <button class="btn" onclick="uploadFolder()" style="background: #28a745;">🚀 Загрузить</button>
            <button class="btn" onclick="clearFiles()" style="background: #dc3545;">Очистить</button>
        </div>
        
        <div class="progress-bar" id="progressBar">
            <div class="progress" id="progress"></div>
        </div>
        
        <div id="status" class="status"></div>
        <div id="log"></div>
    </div>

    <script>
        let selectedFiles = [];
        let userId = 151296248; // ID пользователя в MAX

        const dropZone = document.getElementById('dropZone');
        const folderInput = document.getElementById('folderInput');
        const fileList = document.getElementById('fileList');
        const fileListContent = document.getElementById('fileListContent');
        const statusDiv = document.getElementById('status');
        const logDiv = document.getElementById('log');
        const progressBar = document.getElementById('progressBar');
        const progress = document.getElementById('progress');

        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('dragover');
        });

        dropZone.addEventListener('dragleave', () => {
            dropZone.classList.remove('dragover');
        });

        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            const items = e.dataTransfer.items;
            const files = [];
            for (let item of items) {
                if (item.kind === 'file') {
                    const entry = item.webkitGetAsEntry();
                    if (entry && entry.isDirectory) {
                        readDirectory(entry, files, '');
                    }
                }
            }
            if (files.length > 0) {
                selectedFiles = files;
                displayFiles(selectedFiles);
            }
        });

        folderInput.addEventListener('change', (e) => {
            const files = Array.from(e.target.files);
            if (files.length > 0) {
                selectedFiles = files;
                displayFiles(selectedFiles);
            }
        });

        function readDirectory(entry, files, path) {
            const reader = entry.createReader();
            reader.readEntries((entries) => {
                for (let e of entries) {
                    if (e.isDirectory) {
                        readDirectory(e, files, path + e.name + '/');
                    } else {
                        e.file((file) => {
                            file.webkitRelativePath = path + file.name;
                            files.push(file);
                        });
                    }
                }
            });
        }

        function displayFiles(files) {
            fileListContent.innerHTML = '';
            const folders = new Set();
            files.forEach(f => {
                const parts = f.webkitRelativePath.split('/');
                if (parts.length > 1) {
                    folders.add(parts[0]);
                }
            });
            
            folders.forEach(folder => {
                const li = document.createElement('li');
                const count = files.filter(f => f.webkitRelativePath.startsWith(folder + '/')).length;
                li.textContent = `📁 ${folder} (${count} файлов)`;
                fileListContent.appendChild(li);
            });
            
            fileList.style.display = 'block';
            statusDiv.className = 'status info';
            statusDiv.textContent = `✅ Выбрано ${folders.size} папок, ${files.length} файлов`;
            statusDiv.style.display = 'block';
        }

        function clearFiles() {
            selectedFiles = [];
            fileList.style.display = 'none';
            statusDiv.style.display = 'none';
            progressBar.style.display = 'none';
            logDiv.style.display = 'none';
            folderInput.value = '';
        }

        function addLog(message) {
            logDiv.style.display = 'block';
            logDiv.textContent += message + '\\n';
            logDiv.scrollTop = logDiv.scrollHeight;
        }

        async function uploadFolder() {
            if (selectedFiles.length === 0) {
                showStatus('error', '❌ Выберите папку для загрузки');
                return;
            }

            const formData = new FormData();
            selectedFiles.forEach(file => {
                formData.append('files[]', file, file.webkitRelativePath);
            });
            formData.append('user_id', userId);

            showStatus('info', '⏳ Загрузка началась...');
            progressBar.style.display = 'block';
            progress.style.width = '0%';
            logDiv.textContent = '';
            addLog('🚀 Начинаем загрузку...');
            addLog(`📁 Файлов: ${selectedFiles.length}`);

            try {
                const xhr = new XMLHttpRequest();
                
                xhr.upload.addEventListener('progress', (e) => {
                    if (e.lengthComputable) {
                        const percent = (e.loaded / e.total) * 100;
                        progress.style.width = percent + '%';
                        addLog(`📥 Загружено: ${(e.loaded / 1024 / 1024).toFixed(1)} МБ из ${(e.total / 1024 / 1024).toFixed(1)} МБ (${Math.round(percent)}%)`);
                    }
                });

                xhr.onload = function() {
                    if (xhr.status === 200) {
                        try {
                            const response = JSON.parse(xhr.responseText);
                            if (response.success) {
                                showStatus('success', '✅ Загрузка завершена!');
                                addLog('✅ ' + response.message);
                                progress.style.width = '100%';
                            } else {
                                showStatus('error', '❌ ' + response.message);
                                addLog('❌ Ошибка: ' + response.message);
                            }
                        } catch (e) {
                            showStatus('error', '❌ Ошибка обработки ответа');
                            addLog('❌ Ошибка: ' + e.message);
                        }
                    } else {
                        showStatus('error', '❌ Ошибка загрузки: ' + xhr.status);
                        addLog('❌ Ошибка сервера: ' + xhr.status);
                    }
                };

                xhr.onerror = function() {
                    showStatus('error', '❌ Ошибка соединения');
                    addLog('❌ Ошибка соединения с сервером');
                };

                xhr.open('POST', '/upload_folder');
                xhr.send(formData);
                
            } catch (error) {
                showStatus('error', '❌ Ошибка: ' + error.message);
                addLog('❌ Ошибка: ' + error.message);
            }
        }

        function showStatus(type, message) {
            statusDiv.className = 'status ' + type;
            statusDiv.textContent = message;
            statusDiv.style.display = 'block';
        }
    </script>
</body>
</html>
"""

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
    """Обработка загрузки папки с объявлениями"""
    try:
        user_id = int(request.form.get('user_id', 151296248))
        files = request.files.getlist('files[]')
        
        if not files:
            return jsonify({'success': False, 'message': 'Файлы не выбраны'}), 400
        
        logger.info(f"📥 Получено {len(files)} файлов от пользователя {user_id}")
        
        # Получаем папку пользователя
        user_folder = fm.get_user_folder(user_id)
        temp_folder = os.path.join(user_folder, 'temp_upload')
        
        # Создаём временную папку
        if os.path.exists(temp_folder):
            shutil.rmtree(temp_folder)
        os.makedirs(temp_folder)
        
        # Сохраняем файлы с сохранением структуры папок
        saved_count = 0
        for file in files:
            # Получаем путь из webkitRelativePath
            rel_path = file.filename  # для браузера это webkitRelativePath
            if not rel_path:
                rel_path = file.name
            
            # Сохраняем с сохранением структуры
            full_path = os.path.join(temp_folder, rel_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            file.save(full_path)
            saved_count += 1
            
            if saved_count % 10 == 0:
                logger.info(f"📄 Сохранено {saved_count} файлов")
        
        logger.info(f"✅ Сохранено {saved_count} файлов в {temp_folder}")
        
        # Анализируем структуру папок
        folders = []
        for item in os.listdir(temp_folder):
            item_path = os.path.join(temp_folder, item)
            if os.path.isdir(item_path):
                # Проверяем наличие info.txt
                info_path = os.path.join(item_path, 'info.txt')
                if os.path.exists(info_path):
                    folders.append(item)
                    logger.info(f"📁 Найдена папка объявления: {item}")
                else:
                    logger.warning(f"⚠️ В папке {item} нет info.txt")
        
        if not folders:
            return jsonify({'success': False, 'message': 'Не найдено папок с info.txt'}), 400
        
        # Переносим папки в основную структуру пользователя
        for folder in folders:
            src = os.path.join(temp_folder, folder)
            dst = os.path.join(user_folder, folder)
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.move(src, dst)
            logger.info(f"📦 Перенесена папка {folder}")
        
        # Удаляем временную папку
        shutil.rmtree(temp_folder)
        
        # Запускаем публикацию
        publisher.start(user_id)
        
        return jsonify({
            'success': True,
            'message': f'✅ Загружено {len(folders)} объявлений. Начинаю публикацию!'
        })
        
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки папки: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': str(e)}), 500

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
                "🌐 **Загрузите папку с объявлениями через веб-интерфейс:**\n"
                f"🔗 `https://maxbot.bothost.tech/upload`\n\n"
                "📌 **Требования к папке:**\n"
                "• Внутри папки подпапки с названиями: `Название -123456789`\n"
                "• В каждой подпапке: `info.txt` и изображения\n\n"
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
        return jsonify({"ok": False}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host='0.0.0.0', port=port)
