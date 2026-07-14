from flask import Flask, request, jsonify, render_template_string, send_file
import requests
import logging
import os
import shutil
import urllib3
import json
import threading
import sys
import platform
from modules import Database, FileManager, Publisher, WebInterface
from modules.max_client import ReportGenerator

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024 * 2  # 2 ГБ

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("MAX_TOKEN") or os.environ.get("MAX_BOT_TOKEN") or os.environ.get("TOKEN")
BASE_URL = "https://platform-api2.max.ru"
DATA_DIR = "/app/data"

if not TOKEN:
    logger.error("❌ ТОКЕН НЕ НАЙДЕН!")

db = Database()
fm = FileManager(DATA_DIR)

class APIClient:
    def __init__(self):
        self.token = TOKEN
        self.base_url = BASE_URL

    def send_message(self, user_id, text, attachments=None):
        if not self.token:
            return False
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
            if response.status_code != 200:
                logger.error(f"❌ Ошибка отправки: {response.text}")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
            return False

    def send_message_to_chat(self, chat_id, text):
        if not self.token:
            return False
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
            return response.status_code == 200
        except Exception as e:
            logger.error(f"❌ Ошибка отправки в чат: {e}")
            return False

    def send_photos_to_chat(self, chat_id, photo_files, text=None, caption=None):
        if not self.token:
            return False
        try:
            files = []
            for filename, data in photo_files:
                files.append(('file', (filename, data, 'image/jpeg')))
            data = {"chat_id": chat_id}
            if text:
                data["text"] = text
            if caption:
                data["caption"] = caption
            response = requests.post(
                f"{self.base_url}/messages",
                headers={"Authorization": self.token},
                data=data,
                files=files,
                timeout=120,
                verify=False
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"❌ Ошибка отправки фото: {e}")
            return False

api = APIClient()
publisher = Publisher(api, fm, db)
report_gen = ReportGenerator(fm, db)

# ========== HTML СТРАНИЦА ==========
UPLOAD_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Загрузка объявлений</title>
    <style>
        body { font-family: Arial; max-width: 800px; margin: 50px auto; padding: 20px; background: #f5f5f5; }
        .container { background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1 { color: #333; margin-top: 0; }
        .drop-zone { border: 2px dashed #007bff; padding: 40px; margin: 20px 0; border-radius: 10px; background: #f8f9fa; text-align: center; cursor: pointer; transition: all 0.3s; }
        .drop-zone:hover { background: #e3f2fd; }
        .drop-zone.dragover { background: #d4edda; border-color: #28a745; }
        .drop-zone p { margin: 0; color: #666; }
        .drop-zone .icon { font-size: 48px; display: block; margin-bottom: 10px; }
        input[type="file"] { display: none; }
        .btn { padding: 12px 30px; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; font-weight: bold; transition: all 0.3s; }
        .btn-primary { background: #007bff; color: white; }
        .btn-primary:hover { background: #0056b3; }
        .btn-success { background: #28a745; color: white; }
        .btn-success:hover { background: #218838; }
        .btn-warning { background: #ffc107; color: #333; }
        .btn-warning:hover { background: #e0a800; }
        .btn-danger { background: #dc3545; color: white; }
        .btn-danger:hover { background: #c82333; }
        .status { margin-top: 20px; padding: 15px; border-radius: 5px; display: none; }
        .status.success { background: #d4edda; color: #155724; display: block; border-left: 4px solid #28a745; }
        .status.error { background: #f8d7da; color: #721c24; display: block; border-left: 4px solid #dc3545; }
        .status.info { background: #d1ecf1; color: #0c5460; display: block; border-left: 4px solid #17a2b8; }
        .file-list { text-align: left; margin: 20px 0; padding: 0; list-style: none; }
        .file-list li { background: #f8f9fa; padding: 10px 15px; margin: 5px 0; border-radius: 5px; border-left: 3px solid #007bff; display: flex; justify-content: space-between; align-items: center; }
        .file-list li .count { background: #007bff; color: white; padding: 2px 10px; border-radius: 20px; font-size: 12px; }
        .progress-bar { width: 100%; height: 25px; background: #e9ecef; border-radius: 10px; overflow: hidden; margin: 10px 0; display: none; }
        .progress-bar .progress { height: 100%; background: linear-gradient(90deg, #28a745, #20c997); transition: width 0.3s; width: 0%; display: flex; align-items: center; justify-content: center; color: white; font-size: 12px; font-weight: bold; }
        .instructions { background: #fff3cd; padding: 15px 20px; border-radius: 5px; margin: 20px 0; border-left: 4px solid #ffc107; }
        .instructions code { background: #f8f9fa; padding: 2px 8px; border-radius: 3px; font-size: 14px; color: #d63384; }
        #log { background: #1e1e1e; color: #d4d4d4; padding: 15px; border-radius: 5px; font-family: 'Courier New', monospace; font-size: 12px; max-height: 300px; overflow-y: auto; margin: 20px 0; display: none; white-space: pre-wrap; line-height: 1.5; }
        .button-group { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 15px; }
        .selected-info { background: #e7f5ff; padding: 10px 15px; border-radius: 5px; margin: 10px 0; border-left: 3px solid #007bff; }
        .footer { text-align: center; margin-top: 30px; color: #999; font-size: 14px; }
        .report-section { margin-top: 20px; padding: 15px; background: #f8f9fa; border-radius: 8px; border: 1px solid #dee2e6; }
        .report-section h3 { margin-top: 0; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📤 Загрузка объявлений</h1>
        
        <div class="instructions">
            <strong>📌 Как подготовить папку:</strong><br>
            1️⃣ Создайте папку с названием<br>
            2️⃣ Внутри создайте подпапки: <code>Название -123456789</code><br>
            3️⃣ В каждой подпапке: <code>info.txt</code> и фото<br>
            4️⃣ Перетащите папку в поле ниже
        </div>
        
        <div class="drop-zone" id="dropZone">
            <span class="icon">📂</span>
            <p><strong>Перетащите папку сюда</strong></p>
            <button class="btn btn-primary" onclick="document.getElementById('folderInput').click()">Выбрать папку</button>
            <input type="file" id="folderInput" webkitdirectory multiple>
        </div>
        
        <div id="fileList" style="display:none;">
            <div class="selected-info" id="selectedInfo"></div>
            <ul class="file-list" id="fileListContent"></ul>
            <div class="button-group">
                <button class="btn btn-success" onclick="uploadFolder()">🚀 Загрузить</button>
                <button class="btn btn-warning" onclick="getReport()">📊 Получить отчет</button>
                <button class="btn btn-danger" onclick="clearFiles()">🗑️ Очистить</button>
            </div>
        </div>
        
        <div class="progress-bar" id="progressBar">
            <div class="progress" id="progress">0%</div>
        </div>
        
        <div id="status" class="status"></div>
        <div id="log"></div>
        
        <div class="report-section">
            <h3>📊 Отчеты</h3>
            <p>После публикации вы можете скачать отчет в формате Excel.</p>
            <button class="btn btn-warning" onclick="getReport()">📥 Скачать отчет</button>
            <button class="btn btn-danger" onclick="cleanupData()">🗑️ Очистить данные</button>
            <div id="reportStatus" style="margin-top: 10px;"></div>
        </div>
        
        <div class="footer">⚡ MAX Bot | Загрузка объявлений</div>
    </div>

    <script>
        let selectedFiles = [];
        let userId = 151296248;
        const dropZone = document.getElementById('dropZone');
        const folderInput = document.getElementById('folderInput');
        const fileList = document.getElementById('fileList');
        const fileListContent = document.getElementById('fileListContent');
        const selectedInfo = document.getElementById('selectedInfo');
        const statusDiv = document.getElementById('status');
        const logDiv = document.getElementById('log');
        const progressBar = document.getElementById('progressBar');
        const progress = document.getElementById('progress');

        dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('dragover'); });
        dropZone.addEventListener('dragleave', () => { dropZone.classList.remove('dragover'); });
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
            const fileCount = {};
            files.forEach(f => {
                const parts = f.webkitRelativePath.split('/');
                if (parts.length > 1) {
                    const folder = parts[0];
                    folders.add(folder);
                    if (!fileCount[folder]) fileCount[folder] = 0;
                    fileCount[folder]++;
                }
            });
            folders.forEach(folder => {
                const li = document.createElement('li');
                const count = fileCount[folder] || 0;
                li.innerHTML = `<span>📁 <strong>${folder}</strong></span><span class="count">${count} файлов</span>`;
                fileListContent.appendChild(li);
            });
            selectedInfo.textContent = `✅ Выбрано ${folders.size} папок, всего ${files.length} файлов`;
            fileList.style.display = 'block';
            showStatus('info', '📦 Готово к загрузке!');
        }

        function clearFiles() {
            selectedFiles = [];
            fileList.style.display = 'none';
            statusDiv.style.display = 'none';
            progressBar.style.display = 'none';
            logDiv.style.display = 'none';
            progress.style.width = '0%';
            progress.textContent = '0%';
            folderInput.value = '';
        }

        function addLog(message) {
            logDiv.style.display = 'block';
            logDiv.textContent += message + '\\n';
            logDiv.scrollTop = logDiv.scrollHeight;
        }

        function showStatus(type, message) {
            statusDiv.className = 'status ' + type;
            statusDiv.textContent = message;
            statusDiv.style.display = 'block';
        }

        function uploadFolder() {
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
            progress.textContent = '0%';
            logDiv.textContent = '';
            addLog('🚀 Начинаем загрузку...');
            addLog(`📁 Файлов: ${selectedFiles.length}`);
            try {
                const xhr = new XMLHttpRequest();
                xhr.upload.addEventListener('progress', (e) => {
                    if (e.lengthComputable) {
                        const percent = Math.round((e.loaded / e.total) * 100);
                        progress.style.width = percent + '%';
                        progress.textContent = percent + '%';
                    }
                });
                xhr.onload = function() {
                    if (xhr.status === 200) {
                        try {
                            const response = JSON.parse(xhr.responseText);
                            if (response.success) {
                                showStatus('success', '✅ ' + response.message);
                                addLog('✅ ' + response.message);
                                progress.style.width = '100%';
                                progress.textContent = '100%';
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

        function getReport() {
            const reportStatus = document.getElementById('reportStatus');
            reportStatus.innerHTML = '⏳ Создаю отчет...';
            
            fetch(`/get_report/${userId}`)
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        reportStatus.innerHTML = `✅ Отчет создан! <a href="${data.download_url}" download>Скачать</a>`;
                        addLog('✅ Отчет создан: ' + data.download_url);
                        window.location.href = data.download_url;
                    } else {
                        reportStatus.innerHTML = '❌ ' + data.message;
                        addLog('❌ Ошибка: ' + data.message);
                    }
                })
                .catch(error => {
                    reportStatus.innerHTML = '❌ Ошибка соединения';
                    addLog('❌ Ошибка: ' + error.message);
                });
        }

        function cleanupData() {
            const reportStatus = document.getElementById('reportStatus');
            reportStatus.innerHTML = '⏳ Очищаю данные...';
            
            fetch(`/cleanup/${userId}`, { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        reportStatus.innerHTML = '✅ ' + data.message;
                        addLog('✅ ' + data.message);
                    } else {
                        reportStatus.innerHTML = '❌ ' + data.message;
                        addLog('❌ Ошибка: ' + data.message);
                    }
                })
                .catch(error => {
                    reportStatus.innerHTML = '❌ Ошибка соединения';
                    addLog('❌ Ошибка: ' + error.message);
                });
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
    return render_template_string(UPLOAD_PAGE)

@app.route('/upload_folder', methods=['POST'])
def upload_folder():
    try:
        if 'files[]' not in request.files:
            return jsonify({'success': False, 'message': 'Файлы не найдены'}), 400
        
        files = request.files.getlist('files[]')
        if not files:
            return jsonify({'success': False, 'message': 'Файлы не выбраны'}), 400
        
        user_id = request.form.get('user_id', '151296248')
        try:
            user_id = int(user_id)
        except ValueError:
            user_id = 151296248
        
        logger.info(f"📥 Получено {len(files)} файлов")
        
        user_folder = fm.get_user_folder(user_id)
        if os.path.exists(user_folder):
            shutil.rmtree(user_folder)
        os.makedirs(user_folder, exist_ok=True)
        
        saved_count = 0
        for file in files:
            if not file.filename:
                continue
            rel_path = file.filename
            full_path = os.path.join(user_folder, rel_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            file.save(full_path)
            saved_count += 1
        
        logger.info(f"✅ Сохранено {saved_count} файлов")
        
        threading.Thread(target=publisher.start, args=(user_id,)).start()
        api.send_message(user_id, f"✅ Загружено {saved_count} файлов! Начинаю публикацию...")
        
        return jsonify({'success': True, 'message': f'Загружено {saved_count} файлов'})
        
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки: {e}")
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
        
        if not user_id:
            return jsonify({"ok": True}), 200
        
        logger.info(f"💬 user_id={user_id}, text={text}")
        
        if text and text.strip() == '/start':
            api.send_message(
                user_id,
                "🏠 **Главное меню**\n\n"
                "🌐 **Загрузить папку:**\n"
                f"🔗 https://maxbot.bothost.tech/upload\n\n"
                "📊 **Получить отчет:**\n"
                f"🔗 https://maxbot.bothost.tech/get_report/{user_id}\n\n"
                "🗑️ **Очистить данные:**\n"
                f"🔗 https://maxbot.bothost.tech/cleanup/{user_id}\n\n"
                "⏹ **Остановить публикацию:** `/stop`"
            )
            return jsonify({"ok": True}), 200
        
        if text and text.strip() == '/stop':
            publisher.stop(user_id)
            api.send_message(user_id, "⏹️ Публикация остановлена.")
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
                    f"🔗 [Скачать отчет]({download_url})\n\n"
                    f"⚠️ После скачивания данные будут очищены."
                )
            else:
                api.send_message(user_id, "❌ Нет данных для отчета.")
            return jsonify({"ok": True}), 200
        
        return jsonify({"ok": True}), 200
    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        return jsonify({"ok": False}), 500

@app.route('/get_report/<int:user_id>', methods=['GET'])
def get_report(user_id):
    try:
        report_path = report_gen.generate_report(user_id)
        if not report_path:
            return jsonify({'success': False, 'message': 'Нет данных для отчета'}), 404
        
        filename = os.path.basename(report_path)
        download_url = f"/download_report/{user_id}/{filename}"
        
        return jsonify({
            'success': True,
            'message': 'Отчет создан',
            'download_url': download_url
        })
    except Exception as e:
        logger.error(f"❌ Ошибка создания отчета: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/download_report/<int:user_id>/<path:filename>', methods=['GET'])
def download_report(user_id, filename):
    try:
        user_folder = fm.get_user_folder(user_id)
        file_path = os.path.join(user_folder, filename)
        
        if not os.path.exists(file_path):
            return jsonify({'success': False, 'message': 'Файл не найден'}), 404
        
        response = send_file(file_path, as_attachment=True, download_name=filename)
        
        threading.Thread(target=report_gen.cleanup_user_data, args=(user_id, True)).start()
        
        return response
        
    except Exception as e:
        logger.error(f"❌ Ошибка скачивания отчета: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/cleanup/<int:user_id>', methods=['POST', 'GET'])
def cleanup_user(user_id):
    try:
        report_gen.cleanup_user_data(user_id, keep_report=True)
        return jsonify({'success': True, 'message': 'Данные очищены'})
    except Exception as e:
        logger.error(f"❌ Ошибка очистки: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

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

# ========== ДИАГНОСТИКА ==========

@app.route('/test')
def test():
    """Диагностика бота через браузер - упрощенная версия"""
    result = {
        'status': 'ok',
        'system': {
            'os': platform.system(),
            'python': sys.version,
        },
        'imports': {},
        'files': {},
        'api': {},
        'env': {}
    }
    
    # Проверка импортов
    modules = ['flask', 'requests', 'PIL', 'pandas', 'numpy', 'openpyxl', 'pytz', 'maxapi']
    for mod in modules:
        try:
            __import__(mod)
            result['imports'][mod] = '✅ OK'
        except ImportError as e:
            result['imports'][mod] = f'❌ {str(e)}'
    
    # Проверка файлов
    files = ['app.py', 'requirements.txt', 
             'modules/__init__.py', 'modules/database.py', 
             'modules/file_manager.py', 'modules/publisher.py', 
             'modules/web_interface.py', 'modules/max_client.py']
    for file in files:
        if os.path.exists(file):
            result['files'][file] = f'✅ ({os.path.getsize(file)} байт)'
        else:
            result['files'][file] = '❌ НЕ НАЙДЕН'
    
    # Проверка токена
    token = os.environ.get('MAX_TOKEN') or os.environ.get('MAX_BOT_TOKEN') or os.environ.get('TOKEN')
    if token:
        result['env']['token'] = f'✅ найден (первые 10: {token[:10]}...)'
    else:
        result['env']['token'] = '❌ НЕ НАЙДЕН!'
    
    # Проверка API
    if token:
        try:
            r = requests.get('https://platform-api2.max.ru/me', 
                           headers={'Authorization': token}, 
                           timeout=10, 
                           verify=False)
            result['api']['status'] = r.status_code
            if r.status_code == 200:
                data = r.json()
                result['api']['bot_name'] = data.get('first_name', 'Unknown')
                result['api']['message'] = '✅ API доступен'
            else:
                result['api']['message'] = f'❌ Ошибка: {r.text[:100]}'
        except Exception as e:
            result['api']['message'] = f'❌ {str(e)}'
    else:
        result['api']['message'] = '❌ Токен отсутствует'
    
    # Переменные окружения
    result['env']['PORT'] = os.environ.get('PORT', 'не установлен')
    result['env']['BASE_URL'] = os.environ.get('BASE_URL', 'не установлен')
    
    return jsonify(result)

# ========== ЗАПУСК ==========

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    if TOKEN:
        logger.info(f"✅ Токен найден (первые 10): {TOKEN[:10]}...")
    app.run(host='0.0.0.0', port=port)
