from flask import Flask, request, jsonify, render_template_string
import requests
import logging
import os
import shutil
import urllib3
import json
import time
import random
import re
import base64
import asyncio
from PIL import Image, ExifTags
import io
from modules import Database, FileManager, Publisher, WebInterface

# Импортируем maxapi
try:
    from maxapi import Bot
    from maxapi.types import InputMedia
    MAXAPI_AVAILABLE = True
except ImportError:
    MAXAPI_AVAILABLE = False
    class InputMedia:
        def __init__(self, file_path=None, file_data=None, filename=None):
            self.file_path = file_path
            self.file_data = file_data
            self.filename = filename
    class Bot:
        def __init__(self, token):
            self.token = token

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

# Создаем один event loop для всего приложения
try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

def run_async(coro):
    """Запускает асинхронную функцию в существующем event loop"""
    try:
        if loop.is_running():
            # Если loop уже запущен, создаем задачу
            return asyncio.create_task(coro)
        else:
            # Иначе запускаем через run_until_complete
            return loop.run_until_complete(coro)
    except Exception as e:
        logger.error(f"❌ Ошибка выполнения асинхронной функции: {e}")
        return None

# ========== ИНИЦИАЛИЗАЦИЯ МОДУЛЕЙ ==========
db = Database()
fm = FileManager(DATA_DIR)

class APIClient:
    def __init__(self):
        self.token = TOKEN
        self.base_url = BASE_URL
        if MAXAPI_AVAILABLE:
            self.bot = Bot(token=TOKEN)
            logger.info("✅ Бот MAX API инициализирован")
        else:
            self.bot = None
            logger.warning("⚠️ maxapi не доступна")

    def send_message(self, user_id, text, attachments=None):
        """Отправляет сообщение пользователю"""
        try:
            if MAXAPI_AVAILABLE and self.bot:
                async def send():
                    return await self.bot.send_message(
                        user_id=user_id,
                        text=text,
                        attachments=attachments
                    )
                result = run_async(send())
                logger.info(f"📤 Отправка сообщения пользователю {user_id} через maxapi")
                return True
            else:
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
            if MAXAPI_AVAILABLE and self.bot:
                async def send():
                    return await self.bot.send_message(
                        chat_id=chat_id,
                        text=text
                    )
                result = run_async(send())
                logger.info(f"📤 Отправка сообщения в чат {chat_id} через maxapi")
                return True
            else:
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

    def send_photos_to_chat(self, chat_id, photo_files, caption=None):
        """Отправляет фото в чат используя InputMedia из maxapi"""
        try:
            if MAXAPI_AVAILABLE and self.bot:
                import tempfile
                attachments = []
                
                for filename, data in photo_files:
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
                        tmp.write(data)
                        tmp_path = tmp.name
                    media = InputMedia(tmp_path)
                    attachments.append(media)
                    try:
                        os.unlink(tmp_path)
                    except:
                        pass
                
                async def send():
                    return await self.bot.send_message(
                        chat_id=chat_id,
                        text=caption or f"📸 {len(photo_files)} фото",
                        attachments=attachments
                    )
                result = run_async(send())
                logger.info(f"📤 Отправка {len(photo_files)} фото в чат {chat_id} через maxapi")
                return True
            else:
                # Fallback метод
                success_count = 0
                for idx, (filename, data) in enumerate(photo_files):
                    photo_base64 = base64.b64encode(data).decode('utf-8')
                    attachments = [{
                        "type": "photo",
                        "payload": {
                            "data": photo_base64,
                            "filename": filename
                        }
                    }]
                    if idx == 0 and caption:
                        text = caption
                    else:
                        text = f"📸 Фото {idx+1}/{len(photo_files)}"
                    
                    payload = {
                        "text": text,
                        "format": "markdown",
                        "attachments": attachments
                    }
                    
                    response = requests.post(
                        f"{self.base_url}/messages",
                        headers={
                            "Authorization": self.token,
                            "Content-Type": "application/json"
                        },
                        params={"chat_id": chat_id},
                        json=payload,
                        timeout=60,
                        verify=False
                    )
                    
                    if response.status_code == 200:
                        success_count += 1
                        logger.info(f"✅ Отправлено фото {idx+1}/{len(photo_files)}: {filename}")
                    else:
                        logger.error(f"❌ Ошибка отправки фото {filename}: {response.status_code} {response.text[:200]}")
                    
                    if idx < len(photo_files) - 1:
                        time.sleep(1)
                
                return success_count == len(photo_files)
            
        except Exception as e:
            logger.error(f"❌ Ошибка отправки фото: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    def send_message_to_chat_with_attachments(self, chat_id, text, attachments):
        """Отправляет сообщение с вложениями в чат"""
        try:
            if MAXAPI_AVAILABLE and self.bot:
                async def send():
                    return await self.bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        attachments=attachments
                    )
                result = run_async(send())
                logger.info(f"📤 Отправка с вложениями в чат {chat_id} через maxapi")
                return True
            else:
                payload = {
                    "text": text,
                    "format": "markdown",
                    "attachments": attachments
                }
                response = requests.post(
                    f"{self.base_url}/messages",
                    headers={"Authorization": self.token, "Content-Type": "application/json"},
                    params={"chat_id": chat_id},
                    json=payload,
                    timeout=30,
                    verify=False
                )
                logger.info(f"📤 Отправка с вложениями в чат {chat_id}, статус: {response.status_code}")
                if response.status_code != 200:
                    logger.error(f"❌ Ошибка отправки с вложениями: {response.text}")
                return response.status_code == 200
        except Exception as e:
            logger.error(f"❌ Ошибка отправки с вложениями: {e}")
            return False

api = APIClient()
publisher = Publisher(api, fm, db)
web = WebInterface(fm, publisher)

# ========== ХРАНИЛИЩЕ ДЛЯ ВРЕМЕННЫХ ДАННЫХ ПОЛЬЗОВАТЕЛЕЙ ==========
user_temp_data = {}

# ========== HTML СТРАНИЦА ДЛЯ ЗАГРУЗКИ ПАПКИ ==========
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
    </style>
</head>
<body>
    <div class="container">
        <h1>📤 Загрузка объявлений</h1>
        
        <div class="instructions">
            <strong>📌 Как подготовить папку:</strong><br>
            1️⃣ Создайте папку с названием, например: <code>Мои объявления</code><br>
            2️⃣ Внутри создайте подпапки: <code>Квартиры -123456789</code>, <code>Машины -987654321</code><br>
            3️⃣ В каждой подпапке положите: <code>info.txt</code> (текст объявления) и фото<br>
            4️⃣ Перетащите папку в поле ниже или выберите через кнопку
        </div>
        
        <div class="drop-zone" id="dropZone">
            <span class="icon">📂</span>
            <p><strong>Перетащите папку сюда</strong></p>
            <p style="color: #999; font-size: 14px;">или нажмите кнопку ниже</p>
            <button class="btn btn-primary" onclick="document.getElementById('folderInput').click()">Выбрать папку</button>
            <input type="file" id="folderInput" webkitdirectory multiple>
        </div>
        
        <div id="fileList" style="display:none;">
            <div class="selected-info" id="selectedInfo"></div>
            <ul class="file-list" id="fileListContent"></ul>
            <div class="button-group">
                <button class="btn btn-success" onclick="uploadFolder()">🚀 Загрузить</button>
                <button class="btn btn-danger" onclick="clearFiles()">🗑️ Очистить</button>
            </div>
        </div>
        
        <div class="progress-bar" id="progressBar">
            <div class="progress" id="progress">0%</div>
        </div>
        
        <div id="status" class="status"></div>
        <div id="log"></div>
        
        <div class="footer">
            ⚡ MAX Bot | Загрузка объявлений
        </div>
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
                li.innerHTML = `
                    <span>📁 <strong>${folder}</strong></span>
                    <span class="count">${count} файлов</span>
                `;
                fileListContent.appendChild(li);
            });
            
            selectedInfo.textContent = `✅ Выбрано ${folders.size} папок, всего ${files.length} файлов`;
            fileList.style.display = 'block';
            showStatus('info', '📦 Готово к загрузке! Нажмите "Загрузить"');
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
                        if (percent % 10 === 0) {
                            addLog(`📥 Загружено: ${(e.loaded / 1024 / 1024).toFixed(1)} МБ из ${(e.total / 1024 / 1024).toFixed(1)} МБ (${percent}%)`);
                        }
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
                                if (response.result) {
                                    if (response.result.valid_folders && response.result.valid_folders.length > 0) {
                                        addLog(`✅ Готовы к публикации: ${response.result.valid_folders.join(', ')}`);
                                    }
                                    if (response.result.invalid_folders && response.result.invalid_folders.length > 0) {
                                        addLog(`❌ Пропущены: ${response.result.invalid_folders.join(', ')}`);
                                    }
                                }
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
            return False
            
    except Exception as e:
        logger.error(f"❌ Ошибка отправки кнопок: {e}")
        return False

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
        
        user_folder = fm.get_user_folder(user_id)
        
        if os.path.exists(user_folder):
            shutil.rmtree(user_folder)
            logger.info(f"🗑️ Папка пользователя {user_id} очищена")
        os.makedirs(user_folder, exist_ok=True)
        
        saved_count = 0
        root_folder_name = None
        
        for file in files:
            rel_path = file.filename
            if not rel_path:
                rel_path = file.name
            
            parts = rel_path.split('/')
            
            if len(parts) >= 1 and not root_folder_name:
                root_folder_name = parts[0]
            
            full_path = os.path.join(user_folder, rel_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            file.save(full_path)
            saved_count += 1
        
        logger.info(f"✅ Сохранено {saved_count} файлов")
        logger.info(f"📁 Корневая папка: {root_folder_name}")
        
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
        
        user_temp_data[user_id] = {
            'valid_folders': valid_folders,
            'invalid_folders': invalid_folders,
            'folder_errors': folder_errors
        }
        
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
        
        if invalid_folders and valid_folders:
            api.send_message(
                user_id,
                f"📊 **Результат загрузки:**\n\n{message}\nПубликовать валидные объявления?"
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
                f"✅ **Все папки валидны!**\n\nНайдено {len(valid_folders)} объявлений:\n{', '.join(valid_folders)}\n\n🚀 Начинаем публикацию..."
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
                f"❌ **Нет валидных папок!**\n\n{message}\nПроверьте структуру папок и попробуйте снова."
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

        if payload and isinstance(payload, dict):
            action = payload.get('action')
            if action == 'confirm_publish':
                api.send_message(user_id, "🚀 Начинаю публикацию валидных объявлений...")
                publisher.start(user_id)
                return jsonify({"ok": True}), 200
            elif action == 'cancel_publish':
                api.send_message(user_id, "⏹️ Публикация отменена. Очищаю данные...")
                publisher.stop(user_id)
                return jsonify({"ok": True}), 200

        if text:
            text_lower = text.strip().lower()
            if text_lower == 'да' or text_lower == 'yes':
                api.send_message(user_id, "🚀 Начинаю публикацию валидных объявлений...")
                publisher.start(user_id)
                return jsonify({"ok": True}), 200
            elif text_lower == 'нет' or text_lower == 'no':
                api.send_message(user_id, "⏹️ Публикация отменена. Очищаю данные...")
                publisher.stop(user_id)
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
            api.send_message(user_id, "⏹️ Останавливаю публикацию и очищаю все данные...")
            publisher.stop(user_id)
            api.send_message(user_id, "✅ Публикация остановлена. Все данные очищены.")
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
