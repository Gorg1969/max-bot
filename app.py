# app.py
import os
import sys
import time
import json
import base64
import shutil
import threading
import signal
import logging
from datetime import datetime
from functools import wraps
from html import escape

import requests
import urllib3
from flask import Flask, request, jsonify, render_template_string, send_file, abort
from werkzeug.exceptions import ClientDisconnected, BadRequest
from werkzeug.middleware.proxy_fix import ProxyFix

from modules import Database, FileManager, Publisher, ReportGenerator

# Безопасное отключение предупреждений только в продакшене
if os.environ.get("ENVIRONMENT") == "production":
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
else:
    # В разработке оставляем предупреждения
    pass

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========== КОНФИГУРАЦИЯ ==========
TOKEN = os.environ.get("MAX_TOKEN") or os.environ.get("MAX_BOT_TOKEN") or os.environ.get("TOKEN")
BASE_URL = "https://platform-api2.max.ru"
DATA_DIR = "/app/data"

if not TOKEN:
    logger.error("❌ ТОКЕН НЕ НАЙДЕН!")

# ========== ИНИЦИАЛИЗАЦИЯ ==========
db = Database()
db.fix_publication_times()
fm = FileManager(DATA_DIR)

# ========== СОСТОЯНИЕ ПУБЛИКАЦИИ С ПЕРСИСТЕНТНОСТЬЮ ==========
class PublicationState:
    """Потокобезопасное состояние публикации с сохранением"""
    
    def __init__(self, state_file='/app/data/publication_state.json'):
        self.state_file = state_file
        self._lock = threading.RLock()
        self._data = {
            'is_running': False,
            'is_paused': False,
            'should_stop': False,
            'current_index': 0,
            'total_folders': 0,
            'results': [],
            'user_id': None,
            'delay': 30,
            'started_at': None,
            'updated_at': None
        }
        self._load_state()
    
    def _load_state(self):
        """Загружает состояние из файла"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                    # Восстанавливаем только безопасные поля
                    for key in ['is_running', 'is_paused', 'should_stop', 
                               'current_index', 'total_folders', 'user_id', 'delay']:
                        if key in saved:
                            self._data[key] = saved[key]
                    logger.info(f"📂 Состояние загружено: {self._data}")
        except Exception as e:
            logger.warning(f"⚠️ Не удалось загрузить состояние: {e}")
    
    def _save_state(self):
        """Сохраняет состояние в файл"""
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения состояния: {e}")
    
    def get(self, key, default=None):
        with self._lock:
            return self._data.get(key, default)
    
    def set(self, key, value):
        with self._lock:
            self._data[key] = value
            self._data['updated_at'] = time.time()
            self._save_state()
    
    def update(self, **kwargs):
        with self._lock:
            for key, value in kwargs.items():
                if key in self._data:
                    self._data[key] = value
            self._data['updated_at'] = time.time()
            self._save_state()
    
    def get_all(self):
        with self._lock:
            return self._data.copy()
    
    def reset(self):
        with self._lock:
            self._data = {
                'is_running': False,
                'is_paused': False,
                'should_stop': False,
                'current_index': 0,
                'total_folders': 0,
                'results': [],
                'user_id': None,
                'delay': 30,
                'started_at': None,
                'updated_at': time.time()
            }
            self._save_state()
    
    def add_result(self, folder, success, message):
        with self._lock:
            self._data['results'].append({
                'folder': folder,
                'success': success,
                'message': message,
                'timestamp': time.time()
            })
            # Ограничиваем количество результатов
            if len(self._data['results']) > 1000:
                self._data['results'] = self._data['results'][-500:]
            self._save_state()

# Глобальный экземпляр состояния
publication_state = PublicationState()

# ========== API КЛИЕНТ ==========
class APIClient:
    def __init__(self):
        self.token = TOKEN
        self.base_url = BASE_URL

    def send_message(self, user_id, text, attachments=None):
        if not self.token:
            return False
        for attempt in range(3):
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
                    verify=False if os.environ.get("ENVIRONMENT") == "production" else True
                )
                if response.status_code == 200:
                    return True
                logger.error(f"❌ Попытка {attempt+1}: {response.text}")
                time.sleep(1 * (attempt + 1))
            except Exception as e:
                logger.error(f"❌ Попытка {attempt+1}: {e}")
                time.sleep(2)
        return False

    def send_message_to_chat(self, chat_id, text):
        if not self.token:
            return False
        try:
            payload = {"chat_id": chat_id, "text": text, "format": "markdown"}
            response = requests.post(
                f"{self.base_url}/messages",
                headers={"Authorization": self.token, "Content-Type": "application/json"},
                json=payload,
                timeout=30,
                verify=False if os.environ.get("ENVIRONMENT") == "production" else True
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"❌ Ошибка отправки в чат: {e}")
            return False

    def upload_file(self, image_bytes, filename='image.jpg'):
        if not self.token:
            logger.error("❌ Нет токена для загрузки")
            return None
        for attempt in range(3):
            try:
                response = requests.post(
                    f"{self.base_url}/uploads",
                    headers={"Authorization": self.token},
                    params={"type": "image"},
                    timeout=30,
                    verify=False if os.environ.get("ENVIRONMENT") == "production" else True
                )
                if response.status_code != 200:
                    logger.error(f"❌ Попытка {attempt+1}: {response.status_code}")
                    time.sleep(2)
                    continue
                try:
                    upload_data = response.json()
                except ValueError:
                    logger.error(f"❌ Невалидный JSON: {response.text[:200]}")
                    time.sleep(2)
                    continue
                upload_url = upload_data.get('url')
                if not upload_url:
                    logger.error(f"❌ Не получен URL: {upload_data}")
                    time.sleep(2)
                    continue
                files = {'data': (filename, image_bytes, 'image/jpeg')}
                upload_response = requests.post(
                    upload_url,
                    files=files,
                    timeout=60,
                    verify=False if os.environ.get("ENVIRONMENT") == "production" else True
                )
                if upload_response.status_code != 200:
                    logger.error(f"❌ Ошибка загрузки: {upload_response.status_code}")
                    time.sleep(2)
                    continue
                try:
                    upload_result = upload_response.json()
                except ValueError:
                    logger.error(f"❌ Невалидный JSON: {upload_response.text[:200]}")
                    time.sleep(2)
                    continue
                token = None
                if 'photos' in upload_result and isinstance(upload_result['photos'], dict):
                    for photo_data in upload_result['photos'].values():
                        if isinstance(photo_data, dict) and 'token' in photo_data:
                            token = photo_data['token']
                            break
                if not token and 'token' in upload_result:
                    token = upload_result['token']
                if not token and 'data' in upload_result and 'token' in upload_result['data']:
                    token = upload_result['data']['token']
                if not token:
                    logger.error(f"❌ Не получен токен: {upload_result}")
                    time.sleep(2)
                    continue
                logger.info(f"✅ Файл загружен, токен: {token[:20]}...")
                return token
            except Exception as e:
                logger.error(f"❌ Ошибка, попытка {attempt+1}: {e}")
                time.sleep(2)
        return None


api = APIClient()
publisher = Publisher(api, fm, db)
report_gen = ReportGenerator(fm, db)

# ========== ДЕКОРАТОР БЕЗОПАСНОСТИ ==========
def safe_response(f):
    """Декоратор для безопасной обработки ответов"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ClientDisconnected:
            return jsonify({'success': False, 'message': 'Соединение прервано'}), 400
        except BadRequest as e:
            logger.warning(f"⚠️ Bad request: {e}")
            return jsonify({'success': False, 'message': 'Некорректный запрос'}), 400
        except Exception as e:
            logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
            # В продакшене не показываем детали
            if os.environ.get("ENVIRONMENT") == "production":
                return jsonify({'success': False, 'message': 'Внутренняя ошибка сервера'}), 500
            else:
                return jsonify({'success': False, 'message': str(e)}), 500
    return decorated_function

# ========== HTML СТРАНИЦА ==========
UPLOAD_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Загрузка объявлений</title>
    <style>
        * { box-sizing: border-box; }
        body { font-family: Arial, sans-serif; max-width: 900px; margin: 30px auto; padding: 20px; background: #f0f2f5; }
        .container { background: white; padding: 25px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1 { color: #1a1a2e; margin-top: 0; }
        .drop-zone { border: 3px dashed #4a90d9; padding: 50px 20px; margin: 20px 0; border-radius: 12px; background: #f8f9fa; text-align: center; cursor: pointer; transition: 0.3s; }
        .drop-zone:hover { background: #e3f2fd; border-color: #1a73e8; }
        .drop-zone.dragover { background: #d4edda; border-color: #28a745; }
        .drop-zone .icon { font-size: 48px; display: block; margin-bottom: 10px; }
        input[type="file"] { display: none; }
        .btn { padding: 12px 28px; border: none; border-radius: 6px; cursor: pointer; font-size: 15px; font-weight: 600; transition: 0.3s; }
        .btn-success { background: #28a745; color: white; }
        .btn-success:hover { background: #218838; }
        .btn-danger { background: #dc3545; color: white; }
        .btn-danger:hover { background: #c82333; }
        .btn-warning { background: #ffc107; color: #333; }
        .btn-warning:hover { background: #e0a800; }
        .btn-info { background: #17a2b8; color: white; }
        .btn-info:hover { background: #138496; }
        .btn-primary { background: #007bff; color: white; }
        .btn-primary:hover { background: #0069d9; }
        .btn-secondary { background: #6c757d; color: white; }
        .btn-secondary:hover { background: #5a6268; }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .control-panel { background: #f8f9fa; padding: 15px 20px; border-radius: 8px; margin: 15px 0; border: 1px solid #dee2e6; display: none; }
        .status-badge { display: inline-block; padding: 4px 14px; border-radius: 20px; font-size: 13px; font-weight: bold; }
        .status-badge.idle { background: #6c757d; color: white; }
        .status-badge.running { background: #28a745; color: white; }
        .status-badge.paused { background: #ffc107; color: #333; }
        .status-badge.stopped { background: #dc3545; color: white; }
        .progress-bar { width: 100%; height: 24px; background: #e9ecef; border-radius: 12px; overflow: hidden; margin: 10px 0; display: none; }
        .progress-bar .progress { height: 100%; background: #28a745; transition: width 0.4s; width: 0%; display: flex; align-items: center; justify-content: center; color: white; font-size: 13px; font-weight: bold; }
        .progress-bar .progress.paused { background: #ffc107; }
        .progress-bar .progress.stopped { background: #dc3545; }
        #log { background: #1e1e1e; color: #d4d4d4; padding: 15px; border-radius: 6px; font-family: 'Courier New', monospace; font-size: 12px; max-height: 300px; overflow-y: auto; margin: 15px 0; display: none; white-space: pre-wrap; line-height: 1.6; }
        .status { padding: 12px 18px; border-radius: 6px; margin: 10px 0; display: none; font-weight: 500; }
        .status.success { background: #d4edda; color: #155724; display: block; border-left: 4px solid #28a745; }
        .status.error { background: #f8d7da; color: #721c24; display: block; border-left: 4px solid #dc3545; }
        .status.info { background: #d1ecf1; color: #0c5460; display: block; border-left: 4px solid #17a2b8; }
        .status.warning { background: #fff3cd; color: #856404; display: block; border-left: 4px solid #ffc107; }
        .file-list { list-style: none; padding: 0; margin: 10px 0; max-height: 250px; overflow-y: auto; }
        .file-list li { background: #f8f9fa; padding: 8px 14px; margin: 4px 0; border-radius: 6px; border-left: 3px solid #007bff; display: flex; justify-content: space-between; }
        .file-list li .count { background: #007bff; color: white; padding: 1px 10px; border-radius: 20px; font-size: 12px; }
        .selected-info { background: #e7f5ff; padding: 10px 16px; border-radius: 6px; margin: 10px 0; border-left: 3px solid #007bff; }
        .delay-container { margin: 15px 0; padding: 12px 16px; background: #f0f8ff; border-radius: 8px; display: flex; align-items: center; flex-wrap: wrap; gap: 10px; display: none; }
        .delay-container label { font-weight: 600; }
        .delay-container input[type="range"] { width: 200px; margin: 0 10px; }
        .delay-container .delay-value { font-weight: 600; color: #007bff; min-width: 60px; }
        .button-group { display: flex; gap: 10px; flex-wrap: wrap; margin: 10px 0; }
        .footer { text-align: center; margin-top: 30px; color: #999; font-size: 13px; border-top: 1px solid #eee; padding-top: 20px; }
        .report-section { margin-top: 20px; padding: 20px; background: #f8f9fa; border-radius: 10px; border: 1px solid #dee2e6; text-align: center; }
        #reportStatus { margin-top: 10px; padding: 10px; border-radius: 6px; display: none; font-weight: 500; }
        .instructions { background: #fff3cd; padding: 12px 18px; border-radius: 6px; margin: 15px 0; border-left: 4px solid #ffc107; font-size: 14px; line-height: 1.6; }
        .instructions code { background: #f8f9fa; padding: 2px 8px; border-radius: 4px; font-size: 13px; color: #d63384; }
        @media (max-width: 600px) {
            body { padding: 10px; margin: 10px; }
            .container { padding: 15px; }
            .button-group { flex-direction: column; }
            .btn { width: 100%; }
        }
    </style>
</head>
<body>
<div class="container">
    <h1>📤 Загрузка объявлений</h1>
    
    <div class="instructions">
        <strong>📌 Как подготовить:</strong><br>
        1️⃣ Создайте головную папку<br>
        2️⃣ Внутри — подпапки: <code>1 -id</code>, <code>2 -id</code><br>
        3️⃣ В каждой подпапке: <code>info.txt</code> + фото (до 10 шт)<br>
        4️⃣ Разделитель <code>#изъятая</code> — текст ДО публикуется, ПОСЛЕ идёт в отчёт<br>
        5️⃣ Перетащите головную папку в поле ниже и нажмите <strong>ЗАГРУЗИТЬ</strong>
    </div>
    
    <div class="drop-zone" id="dropZone">
        <span class="icon">📂</span>
        <p><strong>Перетащите головную папку сюда</strong></p>
        <p style="font-size: 14px; color: #888;">или</p>
        <button class="btn btn-primary" onclick="document.getElementById('folderInput').click()">Выбрать папку</button>
        <input type="file" id="folderInput" webkitdirectory multiple>
    </div>
    
    <div id="fileList" style="display:none;">
        <div class="selected-info" id="selectedInfo"></div>
        <ul class="file-list" id="fileListContent"></ul>
    </div>
    
    <div class="delay-container" id="delayContainer">
        <label for="delaySlider">⏱️ Задержка между объявлениями:</label>
        <input type="range" id="delaySlider" min="30" max="120" value="30" 
               oninput="document.getElementById('delayValue').textContent = this.value + ' сек'">
        <span class="delay-value" id="delayValue">30 сек</span>
        <span style="font-size: 12px; color: #666;">(30 сек – 2 минуты)</span>
    </div>
    
    <div class="control-panel" id="controlPanel">
        <div class="button-group">
            <button class="btn btn-success" onclick="uploadFolder()" id="btnUpload">🚀 ЗАГРУЗИТЬ</button>
            <button class="btn btn-warning" onclick="pausePublication()" id="btnPause" style="display:none;">⏸ ПАУЗА</button>
            <button class="btn btn-info" onclick="resumePublication()" id="btnResume" style="display:none;">▶ ПРОДОЛЖИТЬ</button>
            <button class="btn btn-danger" onclick="stopPublication()" id="btnStop" style="display:none;">⏹ СТОП</button>
            <button class="btn btn-secondary" onclick="clearFiles()" id="btnClear">🗑️ Очистить</button>
        </div>
        <div style="margin-top: 10px; font-size: 14px;">
            <span>Статус: </span>
            <span id="publicationStatus" class="status-badge idle">Ожидание</span>
            <span style="margin-left: 15px;" id="progressText"></span>
        </div>
    </div>
    
    <div class="progress-bar" id="progressBar">
        <div class="progress" id="progress">0%</div>
    </div>
    
    <div id="status" class="status"></div>
    <div id="log"></div>
    
    <div class="report-section">
        <div class="button-group" style="justify-content: center;">
            <button class="btn btn-primary" id="reportBtn" onclick="getReport()" disabled>📊 Скачать отчет</button>
            <button class="btn btn-info" onclick="checkReportStatus()">🔄 Проверить статус</button>
            <button class="btn btn-danger" onclick="forceReport()" id="forceReportBtn">📊 Принудительный отчет</button>
        </div>
        <div id="reportStatus"></div>
        <p style="margin-top: 10px; color: #666; font-size: 14px;">После публикации нажмите "Проверить статус"</p>
    </div>
    
    <div class="footer">⚡ MAX Bot | Пауза, Стоп, Отчёт</div>
</div>

<script>
    const userId = 151296248;
    let selectedFiles = [];
    let isProcessing = false;
    let isPaused = false;
    let isStopped = false;
    let reportReady = false;
    let statusCheckInterval = null;
    
    // Элементы
    const dropZone = document.getElementById('dropZone');
    const folderInput = document.getElementById('folderInput');
    const fileList = document.getElementById('fileList');
    const fileListContent = document.getElementById('fileListContent');
    const selectedInfo = document.getElementById('selectedInfo');
    const delayContainer = document.getElementById('delayContainer');
    const controlPanel = document.getElementById('controlPanel');
    const statusDiv = document.getElementById('status');
    const logDiv = document.getElementById('log');
    const progressBar = document.getElementById('progressBar');
    const progress = document.getElementById('progress');
    const reportBtn = document.getElementById('reportBtn');
    const reportStatus = document.getElementById('reportStatus');
    const publicationStatus = document.getElementById('publicationStatus');
    const progressText = document.getElementById('progressText');
    const btnUpload = document.getElementById('btnUpload');
    const btnPause = document.getElementById('btnPause');
    const btnResume = document.getElementById('btnResume');
    const btnStop = document.getElementById('btnStop');
    const btnClear = document.getElementById('btnClear');
    const delaySlider = document.getElementById('delaySlider');
    
    // DROP ZONE
    dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('dragover'); });
    dropZone.addEventListener('dragleave', () => { dropZone.classList.remove('dragover'); });
    
    dropZone.addEventListener('drop', async (e) => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        
        try {
            const items = e.dataTransfer.items;
            const files = [];
            
            for (let item of items) {
                if (item.kind === 'file') {
                    const entry = item.webkitGetAsEntry();
                    if (entry) {
                        if (entry.isDirectory) {
                            await readDirectory(entry, files, '');
                        } else {
                            const file = await new Promise((resolve, reject) => {
                                entry.file(resolve, reject);
                            });
                            file.webkitRelativePath = entry.name;
                            files.push(file);
                        }
                    }
                }
            }
            
            if (files.length > 0) {
                selectedFiles = files;
                displayFiles(selectedFiles);
                showStatus('info', `📦 Загружено ${files.length} файлов`);
            } else {
                showStatus('warning', '⚠️ Папка пуста или не выбрана');
            }
        } catch (error) {
            console.error('Ошибка:', error);
            showStatus('error', '❌ Ошибка при чтении папки: ' + error.message);
        }
    });
    
    folderInput.addEventListener('change', (e) => {
        const files = Array.from(e.target.files);
        if (files.length > 0) {
            selectedFiles = files;
            displayFiles(selectedFiles);
        }
    });
    
    async function readDirectory(entry, files, path) {
        return new Promise((resolve) => {
            const reader = entry.createReader();
            const allEntries = [];
            
            const readEntries = () => {
                reader.readEntries((entries) => {
                    if (entries.length === 0) {
                        processEntries(allEntries);
                        return;
                    }
                    allEntries.push(...entries);
                    readEntries();
                }, (error) => {
                    console.error('Ошибка чтения папки:', error);
                    resolve();
                });
            };
            
            const processEntries = (entries) => {
                let pending = entries.length;
                if (pending === 0) {
                    resolve();
                    return;
                }
                
                for (let e of entries) {
                    if (e.isDirectory) {
                        readDirectory(e, files, path + e.name + '/').then(() => {
                            pending--;
                            if (pending === 0) resolve();
                        });
                    } else {
                        e.file((file) => {
                            file.webkitRelativePath = path + file.name;
                            files.push(file);
                            pending--;
                            if (pending === 0) resolve();
                        }, (error) => {
                            console.error('Ошибка чтения файла:', error);
                            pending--;
                            if (pending === 0) resolve();
                        });
                    }
                }
            };
            
            readEntries();
        });
    }
    
    function displayFiles(files) {
        fileListContent.innerHTML = '';
        
        const folders = new Map();
        files.forEach(f => {
            const relPath = f.webkitRelativePath || f.name;
            const parts = relPath.split('/');
            if (parts.length >= 2) {
                const folderKey = parts[0];
                const subFolder = parts.slice(0, 2).join('/');
                
                if (!folders.has(folderKey)) {
                    folders.set(folderKey, new Map());
                }
                const subFolders = folders.get(folderKey);
                if (!subFolders.has(subFolder)) {
                    subFolders.set(subFolder, []);
                }
                subFolders.get(subFolder).push(f);
            }
        });
        
        let totalFolders = 0;
        for (const [rootFolder, subFolders] of folders) {
            const header = document.createElement('li');
            header.style.fontWeight = 'bold';
            header.style.background = '#e3f2fd';
            header.textContent = `📁 ${rootFolder}`;
            fileListContent.appendChild(header);
            
            for (const [subFolder, files] of subFolders) {
                const li = document.createElement('li');
                const displayName = subFolder.split('/').pop() || subFolder;
                const fileTypes = files.map(f => {
                    if (f.name === 'info.txt' || f.name.endsWith('.txt')) return '📄';
                    if (f.type && f.type.startsWith('image/')) return '🖼️';
                    return '📎';
                });
                const uniqueTypes = [...new Set(fileTypes)];
                li.innerHTML = `<span>📂 ${displayName}</span><span class="count">${files.length} файлов (${uniqueTypes.join(' ')})</span>`;
                fileListContent.appendChild(li);
                totalFolders++;
            }
        }
        
        selectedInfo.textContent = `✅ Найдено ${totalFolders} папок с объявлениями, всего ${files.length} файлов`;
        fileList.style.display = 'block';
        delayContainer.style.display = 'flex';
        controlPanel.style.display = 'block';
        btnUpload.disabled = false;
        showStatus('info', '📦 Нажмите "ЗАГРУЗИТЬ" для начала');
    }
    
    function clearFiles() {
        if (isProcessing && !isPaused) {
            if (!confirm('⚠️ Идёт публикация. Остановить?')) return;
        }
        selectedFiles = [];
        fileList.style.display = 'none';
        delayContainer.style.display = 'none';
        controlPanel.style.display = 'none';
        statusDiv.style.display = 'none';
        progressBar.style.display = 'none';
        logDiv.style.display = 'none';
        progress.style.width = '0%';
        progress.textContent = '0%';
        folderInput.value = '';
        isStopped = false;
        isPaused = false;
        reportReady = false;
        reportBtn.disabled = true;
        reportStatus.style.display = 'none';
        btnPause.style.display = 'none';
        btnResume.style.display = 'none';
        btnStop.style.display = 'none';
        btnUpload.disabled = true;
        publicationStatus.className = 'status-badge idle';
        publicationStatus.textContent = 'Ожидание';
        progressText.textContent = '';
    }
    
    function showStatus(type, message) {
        statusDiv.className = 'status ' + type;
        statusDiv.textContent = message;
        statusDiv.style.display = 'block';
    }
    
    function addLog(message) {
        logDiv.style.display = 'block';
        logDiv.textContent += message + '\n';
        logDiv.scrollTop = logDiv.scrollHeight;
    }
    
    // ПАУЗА
    async function pausePublication() {
        try {
            const response = await fetch('/pause_publication', { 
                method: 'POST', 
                headers: { 'Content-Type': 'application/json' } 
            });
            const result = await response.json();
            
            if (result.success) {
                showStatus('info', '⏸ Публикация на паузе');
                addLog('⏸ ПАУЗА');
                isPaused = true;
                btnPause.style.display = 'none';
                btnResume.style.display = 'inline-block';
                btnStop.style.display = 'inline-block';
                publicationStatus.className = 'status-badge paused';
                publicationStatus.textContent = 'На паузе';
                progress.className = 'progress paused';
            } else {
                showStatus('error', '❌ ' + result.message);
            }
        } catch (error) {
            showStatus('error', '❌ ' + error.message);
            addLog('❌ Ошибка паузы: ' + error.message);
        }
    }
    
    // ПРОДОЛЖИТЬ
    async function resumePublication() {
        try {
            const response = await fetch('/resume_publication', { 
                method: 'POST', 
                headers: { 'Content-Type': 'application/json' } 
            });
            const result = await response.json();
            
            if (result.success) {
                showStatus('info', '▶ Публикация продолжена');
                addLog('▶ ПРОДОЛЖЕНИЕ');
                isPaused = false;
                isStopped = false;
                btnPause.style.display = 'inline-block';
                btnResume.style.display = 'none';
                btnStop.style.display = 'inline-block';
                publicationStatus.className = 'status-badge running';
                publicationStatus.textContent = 'Выполняется';
                progress.className = 'progress';
                
                if (isProcessing) {
                    uploadFolder();
                }
            } else {
                showStatus('error', '❌ ' + result.message);
            }
        } catch (error) {
            showStatus('error', '❌ ' + error.message);
            addLog('❌ Ошибка продолжения: ' + error.message);
        }
    }
    
    // СТОП
    async function stopPublication() {
        if (!confirm('⏹ Остановить публикацию и создать отчёт?')) return;
        
        try {
            showStatus('info', '⏳ Остановка и создание отчета...');
            btnStop.disabled = true;
            
            const response = await fetch('/stop_publication', { 
                method: 'POST', 
                headers: { 'Content-Type': 'application/json' } 
            });
            const result = await response.json();
            
            if (result.success) {
                showStatus('success', `✅ ${result.message}`);
                addLog(`📊 Остановлено: ${result.processed} папок, успешно: ${result.success_count || 0}, ошибок: ${result.error_count || 0}`);
                
                btnPause.style.display = 'none';
                btnResume.style.display = 'none';
                btnStop.style.display = 'none';
                btnUpload.disabled = false;
                btnClear.disabled = false;
                
                if (result.report_url) {
                    reportBtn.disabled = false;
                    reportReady = true;
                    addLog(`📊 Отчёт: ${result.report_url}`);
                    
                    setTimeout(() => {
                        window.open(result.report_url, '_blank');
                    }, 2000);
                }
                
                publicationStatus.className = 'status-badge stopped';
                publicationStatus.textContent = 'Остановлено';
                progress.className = 'progress stopped';
                isProcessing = false;
                isStopped = true;
                
            } else {
                showStatus('error', '❌ ' + result.message);
            }
        } catch (error) {
            showStatus('error', '❌ ' + error.message);
            addLog('❌ Ошибка остановки: ' + error.message);
        } finally {
            btnStop.disabled = false;
        }
    }
    
    // ЗАГРУЗКА
    async function uploadFolder() {
        if (selectedFiles.length === 0) {
            showStatus('error', '❌ Выберите папку');
            return;
        }
        
        try {
            const statusResponse = await fetch('/publication_status');
            const statusData = await statusResponse.json();
            if (statusData.is_running && !statusData.is_paused) {
                showStatus('warning', '⚠️ Публикация уже выполняется');
                return;
            }
            if (statusData.is_paused) {
                showStatus('info', '⏸ На паузе. Нажмите "ПРОДОЛЖИТЬ"');
                return;
            }
        } catch (e) {}
        
        isProcessing = true;
        isStopped = false;
        isPaused = false;
        btnUpload.disabled = true;
        btnClear.disabled = true;
        btnPause.style.display = 'inline-block';
        btnStop.style.display = 'inline-block';
        btnResume.style.display = 'none';
        publicationStatus.className = 'status-badge running';
        publicationStatus.textContent = 'Выполняется';
        
        const delay = delaySlider ? parseInt(delaySlider.value) : 30;
        addLog(`⏱️ Задержка: ${delay} сек`);
        showStatus('info', '⏳ Подготовка...');
        progressBar.style.display = 'block';
        progress.style.width = '0%';
        progress.textContent = '0%';
        logDiv.textContent = '';
        addLog('🚀 Начинаем обработку...');
        
        const folders = new Map();
        selectedFiles.forEach(file => {
            const relPath = file.webkitRelativePath || file.name;
            const parts = relPath.split('/');
            if (parts.length >= 2) {
                const folderKey = parts.slice(0, 2).join('/');
                if (!folders.has(folderKey)) {
                    folders.set(folderKey, []);
                }
                folders.get(folderKey).push(file);
            }
        });
        
        const folderNames = Array.from(folders.keys());
        const totalFolders = folderNames.length;
        addLog(`📁 Найдено ${totalFolders} папок`);
        
        let successCount = 0;
        let errorCount = 0;
        
        for (let i = 0; i < folderNames.length; i++) {
            try {
                const statusResponse = await fetch('/publication_status');
                const statusData = await statusResponse.json();
                if (statusData.is_paused) {
                    addLog(`⏸ ПАУЗА на папке ${i+1}/${totalFolders}`);
                    isPaused = true;
                    progress.className = 'progress paused';
                    btnPause.style.display = 'none';
                    btnResume.style.display = 'inline-block';
                    publicationStatus.className = 'status-badge paused';
                    publicationStatus.textContent = 'На паузе';
                    return;
                }
                if (statusData.should_stop || !statusData.is_running) {
                    addLog('⏹ Остановлено');
                    break;
                }
            } catch (e) {}
            
            if (isStopped) break;
            
            const folderName = folderNames[i];
            const files = folders.get(folderName);
            const percent = Math.round(((i + 1) / totalFolders) * 100);
            progress.style.width = percent + '%';
            progress.textContent = `${i+1}/${totalFolders}`;
            progressText.textContent = `📊 ${i+1}/${totalFolders} папок`;
            showStatus('info', `⏳ ${i+1}/${totalFolders}: ${folderName}`);
            
            try {
                addLog(`📤 ${i+1}/${totalFolders}: ${folderName}`);
                const folderData = await prepareFolderData(folderName, files);
                if (!folderData) {
                    addLog(`⚠️ Пропускаем: нет info.txt`);
                    errorCount++;
                    continue;
                }
                const response = await fetch('/publish_folder', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        user_id: parseInt(userId),
                        folder: folderData,
                        delay: delay
                    })
                });
                const result = await response.json();
                if (result.success) {
                    successCount++;
                    addLog(`✅ ${folderName}: опубликовано`);
                } else {
                    errorCount++;
                    addLog(`❌ ${folderName}: ${result.message}`);
                }
            } catch (error) {
                errorCount++;
                addLog(`❌ ${folderName}: ошибка`);
            }
            
            try {
                const statusResponse = await fetch('/publication_status');
                const statusData = await statusResponse.json();
                if (statusData.should_stop || !statusData.is_running) {
                    addLog('⏹ Остановлено после папки');
                    break;
                }
            } catch (e) {}
            
            await new Promise(r => setTimeout(r, 2000));
        }
        
        progress.style.width = '100%';
        progress.textContent = `${totalFolders}/${totalFolders}`;
        progressText.textContent = `✅ ${totalFolders}/${totalFolders} папок`;
        showStatus('success', `✅ Загружено ${successCount} папок, ошибок: ${errorCount}`);
        addLog(`📊 Завершено: ${successCount} успешно, ${errorCount} ошибок`);
        
        btnUpload.disabled = false;
        btnClear.disabled = false;
        btnPause.style.display = 'none';
        btnStop.style.display = 'none';
        isProcessing = false;
        publicationStatus.className = 'status-badge idle';
        publicationStatus.textContent = 'Ожидание';
        
        setTimeout(() => { addLog('🔄 Проверка статуса...'); checkReportStatus(); }, 30000);
    }
    
    // ПОДГОТОВКА ПАПКИ
    async function prepareFolderData(folderPath, files) {
        const txtFile = files.find(f => {
            const relPath = f.webkitRelativePath || f.name;
            return relPath.startsWith(folderPath) && 
                   (f.name === 'info.txt' || f.name.endsWith('.txt'));
        });
        
        if (!txtFile) {
            addLog(`⚠️ В папке ${folderPath} нет info.txt`);
            return null;
        }
        
        let fullText = await txtFile.text();
        let adText = fullText;
        let metadataText = '';
        
        if (fullText.includes('#изъятая')) {
            const parts = fullText.split('#изъятая');
            adText = parts[0].trim();
            metadataText = parts[1] ? parts[1].trim() : '';
        }
        
        const imageFiles = files.filter(f => {
            const relPath = f.webkitRelativePath || f.name;
            return relPath.startsWith(folderPath) && 
                   f.type && f.type.startsWith('image/');
        }).slice(0, 10);
        
        const imageTokens = [];
        for (const img of imageFiles) {
            if (isStopped) break;
            const token = await uploadSinglePhoto(img, userId, folderPath);
            if (token) imageTokens.push(token);
            await new Promise(r => setTimeout(r, 300));
        }
        
        return {
            folderName: folderPath,
            adText: adText,
            metadataText: metadataText,
            fullText: fullText,
            imageTokens: imageTokens
        };
    }
    
    // ЗАГРУЗКА ФОТО
    async function uploadSinglePhoto(file, user_id, folder_name) {
        try {
            const formData = new FormData();
            formData.append('photo', file);
            formData.append('user_id', user_id);
            formData.append('folder_name', folder_name);
            const response = await fetch('/upload_photo', {
                method: 'POST',
                body: formData
            });
            const result = await response.json();
            if (result.success) {
                return result.token;
            }
            return null;
        } catch (error) {
            addLog(`❌ Ошибка фото ${file.name}`);
            return null;
        }
    }
    
    // ОТЧЁТЫ
    function getReport() {
        if (!reportReady) {
            showStatus('warning', '⏳ Отчёт ещё не готов');
            return;
        }
        window.open(`/report/${userId}`, '_blank');
    }
    
    async function checkReportStatus() {
        try {
            const response = await fetch(`/report_status/${userId}`);
            const result = await response.json();
            
            reportStatus.style.display = 'block';
            let text = `📊 Всего: ${result.total} | ✅ Готово: ${result.success}`;
            
            if (result.pending > 0) {
                text += ` | ⏳ Ожидают: ${result.pending}`;
                reportStatus.className = 'status info';
                reportBtn.disabled = true;
                reportReady = false;
                
                if (result.failed > 0) {
                    text += ` | ❌ Ошибок: ${result.failed}`;
                }
            } else if (result.success > 0 || result.failed > 0) {
                text += '\n✅ Отчет готов!';
                reportStatus.className = 'status success';
                reportBtn.disabled = false;
                reportReady = true;
            } else {
                text += '\n⏳ Нет публикаций';
                reportStatus.className = 'status info';
                reportBtn.disabled = true;
                reportReady = false;
            }
            
            reportStatus.textContent = text;
            addLog('📊 ' + text);
            
        } catch (error) {
            reportStatus.style.display = 'block';
            reportStatus.className = 'status error';
            reportStatus.textContent = '❌ ' + error.message;
            addLog('❌ Ошибка проверки статуса: ' + error.message);
        }
    }
    
    // ПРИНУДИТЕЛЬНЫЙ ОТЧЕТ
    async function forceReport() {
        try {
            showStatus('info', '⏳ Создание принудительного отчета...');
            const response = await fetch(`/force_report/${userId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            const result = await response.json();
            
            if (result.success) {
                showStatus('success', '✅ Отчет создан!');
                reportReady = true;
                reportBtn.disabled = false;
                window.open(result.report_url, '_blank');
                addLog('📊 Принудительный отчет: ' + result.report_url);
            } else {
                showStatus('error', '❌ ' + result.message);
            }
        } catch (error) {
            showStatus('error', '❌ ' + error.message);
        }
    }
</script>
</body>
</html>
"""

# ========== МАРШРУТЫ ==========

@app.route('/', methods=['GET', 'POST'])
@safe_response
def index():
    if request.method == 'POST':
        return webhook()
    return "🤖 MAX Bot is running! Webhook endpoint: /webhook"


@app.route('/upload', methods=['GET'])
@safe_response
def upload_page():
    return render_template_string(UPLOAD_PAGE)


@app.route('/upload_photo', methods=['POST'])
@safe_response
def upload_photo():
    try:
        photo = request.files.get('photo')
        user_id = request.form.get('user_id')
        folder_name = request.form.get('folder_name')
        
        if not photo:
            return jsonify({'success': False, 'message': 'Нет фото'}), 400
        if not user_id:
            return jsonify({'success': False, 'message': 'Нет user_id'}), 400
        
        # Проверяем размер фото
        photo.seek(0, os.SEEK_END)
        size = photo.tell()
        photo.seek(0)
        if size > 20 * 1024 * 1024:  # 20MB
            return jsonify({'success': False, 'message': 'Фото слишком большое'}), 400
        
        image_bytes = photo.read()
        logger.info(f"📸 Загрузка фото {photo.filename}, размер: {len(image_bytes)} байт")
        token = api.upload_file(image_bytes, photo.filename)
        
        if token:
            logger.info(f"✅ Фото загружено, токен: {token[:20]}...")
            return jsonify({'success': True, 'token': token})
        else:
            return jsonify({'success': False, 'message': 'Не удалось загрузить фото'}), 500
        
    except ClientDisconnected:
        return jsonify({'success': False, 'message': 'Соединение прервано'}), 400
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки фото: {e}")
        return jsonify({'success': False, 'message': 'Ошибка загрузки фото'}), 500


@app.route('/publish_folder', methods=['POST'])
@safe_response
def publish_folder():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        folder_data = data.get('folder')
        delay = data.get('delay', 30)
        delay = max(30, min(120, delay))
        
        if not user_id or not folder_data:
            return jsonify({'success': False, 'message': 'Нет данных'}), 400
        
        if publication_state.get('should_stop'):
            return jsonify({'success': False, 'message': 'Публикация остановлена'}), 409
        
        # Запускаем публикацию в фоновом потоке, чтобы не блокировать запрос
        def publish_in_background():
            try:
                # Проверяем состояние
                if publication_state.get('should_stop'):
                    return
                
                if not publication_state.get('is_running'):
                    publication_state.update(
                        is_running=True,
                        is_paused=False,
                        should_stop=False,
                        user_id=user_id,
                        delay=delay,
                        current_index=0,
                        started_at=time.time()
                    )
                
                if publication_state.get('is_paused'):
                    return
                
                if publication_state.get('should_stop'):
                    return
                
                folder_name = folder_data.get('folderName')
                ad_text = folder_data.get('adText')
                metadata_text = folder_data.get('metadataText')
                image_tokens = folder_data.get('imageTokens', [])
                
                logger.info(f"📦 Папка: {folder_name} от {user_id}, задержка: {delay}с")
                
                success, message = publisher.publish_folder_with_tokens(
                    user_id, folder_name, ad_text, metadata_text, image_tokens
                )
                
                publication_state.add_result(folder_name, success, message)
                publication_state.set('current_index', publication_state.get('current_index', 0) + 1)
                
                if publication_state.get('should_stop'):
                    logger.info(f"⏹ Остановка после папки {folder_name}")
                    return
                
                if delay > 0 and success:
                    logger.info(f"⏱️ Задержка {delay} сек")
                    # Разбиваем задержку на интервалы для проверки остановки
                    for _ in range(delay):
                        if publication_state.get('should_stop') or publication_state.get('is_paused'):
                            break
                        time.sleep(1)
                        
            except Exception as e:
                logger.error(f"❌ Ошибка в фоновой публикации: {e}")
        
        # Запускаем в фоновом потоке
        thread = threading.Thread(target=publish_in_background, daemon=True)
        thread.start()
        
        return jsonify({
            'success': True,
            'message': 'Публикация запущена в фоне',
            'folder': folder_data.get('folderName')
        })
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({'success': False, 'message': 'Ошибка публикации'}), 500


@app.route('/pause_publication', methods=['POST'])
@safe_response
def pause_publication():
    if not publication_state.get('is_running'):
        return jsonify({'success': False, 'message': 'Нет активной публикации'}), 400
    
    if publication_state.get('is_paused'):
        return jsonify({'success': False, 'message': 'Уже на паузе'}), 400
    
    publication_state.set('is_paused', True)
    logger.info(f"⏸ ПАУЗА: публикация остановлена для {publication_state.get('user_id')}")
    
    return jsonify({
        'success': True,
        'message': '⏸ Публикация на паузе',
        'current_index': publication_state.get('current_index', 0),
        'total': publication_state.get('total_folders', 0)
    })


@app.route('/resume_publication', methods=['POST'])
@safe_response
def resume_publication():
    if not publication_state.get('is_paused'):
        return jsonify({'success': False, 'message': 'Публикация не на паузе'}), 400
    
    if publication_state.get('should_stop'):
        return jsonify({'success': False, 'message': 'Публикация остановлена'}), 400
    
    publication_state.set('is_paused', False)
    publication_state.set('is_running', True)
    logger.info(f"▶ ПРОДОЛЖЕНИЕ: публикация возобновлена для {publication_state.get('user_id')}")
    
    return jsonify({
        'success': True,
        'message': '▶ Публикация продолжена',
        'current_index': publication_state.get('current_index', 0),
        'total': publication_state.get('total_folders', 0)
    })


@app.route('/stop_publication', methods=['POST'])
@safe_response
def stop_publication():
    if not publication_state.get('is_running') and not publication_state.get('is_paused'):
        if publication_state.get('results'):
            user_id = publication_state.get('user_id')
            if user_id:
                report_path = report_gen.generate_report(user_id)
                if report_path:
                    filename = os.path.basename(report_path)
                    report_url = f"/download_report/{user_id}/{filename}"
                    return jsonify({
                        'success': True,
                        'message': '📊 Отчет создан',
                        'report_url': report_url,
                        'processed': len(publication_state.get('results', []))
                    })
        return jsonify({'success': False, 'message': 'Нет активной публикации'}), 400
    
    user_id = publication_state.get('user_id')
    publication_state.set('should_stop', True)
    publication_state.set('is_running', False)
    publication_state.set('is_paused', False)
    
    logger.info(f"⏹ СТОП: публикация завершена для {user_id}")
    
    report_url = None
    if user_id:
        try:
            time.sleep(1)
            report_path = report_gen.generate_report(user_id)
            if report_path:
                filename = os.path.basename(report_path)
                report_url = f"/download_report/{user_id}/{filename}"
                logger.info(f"📊 Отчет создан при остановке: {report_path}")
                
                try:
                    api.send_message(
                        user_id,
                        f"⏹ **Публикация остановлена!**\n\n"
                        f"📊 **Отчёт создан:** [Скачать]({report_url})\n\n"
                        f"📦 Обработано: {len(publication_state.get('results', []))} папок\n"
                        f"✅ Успешно: {len([r for r in publication_state.get('results', []) if r.get('success')])}\n"
                        f"❌ Ошибок: {len([r for r in publication_state.get('results', []) if not r.get('success')])}"
                    )
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки уведомления: {e}")
            else:
                logger.warning(f"⚠️ Не удалось создать отчет для {user_id}")
        except Exception as e:
            logger.error(f"❌ Ошибка создания отчета: {e}")
    
    results = publication_state.get('results', [])
    result = {
        'success': True,
        'message': '⏹ Публикация остановлена, отчёт создан',
        'report_url': report_url,
        'processed': len(results),
        'success_count': len([r for r in results if r.get('success')]),
        'error_count': len([r for r in results if not r.get('success')])
    }
    
    # Не сбрасываем should_stop сразу, чтобы дать завершиться фоновым задачам
    def reset_state():
        time.sleep(10)
        publication_state.set('should_stop', False)
    
    threading.Thread(target=reset_state, daemon=True).start()
    
    return jsonify(result)


@app.route('/publication_status', methods=['GET'])
@safe_response
def publication_status():
    state = publication_state.get_all()
    return jsonify({
        'is_running': state.get('is_running', False),
        'is_paused': state.get('is_paused', False),
        'should_stop': state.get('should_stop', False),
        'current_index': state.get('current_index', 0),
        'total_folders': state.get('total_folders', 0),
        'user_id': state.get('user_id'),
        'results_count': len(state.get('results', []))
    })


@app.route('/webhook', methods=['GET', 'POST'])
@safe_response
def webhook():
    if request.method == 'GET':
        webhook_url = os.environ.get("WEBHOOK_URL", "https://maxbot.bothost.tech")
        return jsonify({
            "status": "ok",
            "message": "Webhook is ready",
            "webhook_url": webhook_url
        }), 200
    
    try:
        data = request.get_json()
        logger.info(f"📩 ПОЛУЧЕН ВЕБХУК: {data}")
        
        if not data:
            return jsonify({"ok": True}), 200
        
        update_type = data.get('update_type')
        
        if update_type == 'message_created':
            logger.info("📨 Получено событие message_created")
            message = data.get('message', {})
            recipient = message.get('recipient', {})
            sender = message.get('sender', {})
            body = message.get('body', {})
            
            chat_id = recipient.get('chat_id')
            user_id = sender.get('user_id')
            text = body.get('text', '')
            message_id = body.get('mid')
            
            # Проверяем наличие chat_id
            if chat_id is not None:
                chat_id = str(chat_id)
            else:
                logger.warning("⚠️ Вебхук без chat_id")
                return jsonify({"ok": True}), 200
            
            logger.info(f"📨 chat_id: {chat_id}, user_id: {user_id}, text: {text[:50] if text else ''}")
            
            if user_id and text:
                if text.strip() == '/start':
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
                        "3. Фото до 10 шт на объявление"
                    )
                    return jsonify({"ok": True}), 200
                
                if text.strip() == '/stop':
                    if publication_state.get('is_running') or publication_state.get('is_paused'):
                        stop_publication()
                    publisher.stop(user_id)
                    api.send_message(user_id, "⏹️ **Публикация остановлена!**")
                    return jsonify({"ok": True}), 200
                
                if text.strip() == '/stat':
                    logger.info(f"📊 Запрос статистики для {user_id}")
                    try:
                        stats = db.get_stats(user_id)
                        message = (
                            "📊 **Статистика публикаций**\n\n"
                            f"📦 Всего папок: {stats.get('total', 0)}\n"
                            f"✅ Успешно: {stats.get('success', 0)}\n"
                            f"⏳ В обработке: {stats.get('pending', 0)}\n"
                            f"❌ Ошибок: {stats.get('errors', 0)}\n"
                        )
                        api.send_message(user_id, message)
                    except Exception as e:
                        logger.error(f"❌ Ошибка статистики: {e}")
                        api.send_message(user_id, f"❌ Ошибка: {str(e)}")
                    return jsonify({"ok": True}), 200
                
                if text.strip() == '/report':
                    api.send_message(user_id, "📊 Создаю отчет...")
                    report_path = report_gen.generate_report(user_id)
                    if report_path:
                        filename = os.path.basename(report_path)
                        download_url = f"https://maxbot.bothost.tech/download_report/{user_id}/{filename}"
                        api.send_message(user_id, f"📊 **Отчет создан!**\n\n🔗 [Скачать отчет]({download_url})")
                    else:
                        api.send_message(user_id, "❌ Нет данных для отчета.")
                    return jsonify({"ok": True}), 200
            
            if chat_id and message_id:
                logger.info(f"📨 Получен ID: {message_id} для чата {chat_id}")
                if user_id:
                    publisher.handle_message_created(chat_id, message_id, user_id)
                else:
                    publisher.handle_message_created(chat_id, message_id)
                return jsonify({"ok": True}), 200
            
            return jsonify({"ok": True}), 200
        
        if update_type in ['bot_stopped', 'bot_started']:
            logger.info(f"📨 Получено событие {update_type}")
            return jsonify({"ok": True}), 200
        
        logger.info(f"ℹ️ Вебхук с update_type: {update_type}")
        return jsonify({"ok": True}), 200
        
    except Exception as e:
        logger.error(f"❌ ОШИБКА В ВЕБХУКЕ: {e}")
        return jsonify({"ok": False}), 500


@app.route('/setup_webhook', methods=['GET', 'POST'])
@safe_response
def setup_webhook():
    token = request.args.get('token') or TOKEN
    if not token:
        return "❌ Токен не найден", 400
    
    webhook_url = os.environ.get("WEBHOOK_URL", "https://maxbot.bothost.tech")
    headers = {"Authorization": token, "Content-Type": "application/json"}
    
    try:
        payload = {
            "url": webhook_url,
            "update_types": ["message_created", "bot_started", "bot_stopped"]
        }
        
        r = requests.post(
            "https://platform-api2.max.ru/subscriptions",
            headers=headers,
            json=payload,
            timeout=30,
            verify=False if os.environ.get("ENVIRONMENT") == "production" else True
        )
        
        if r.status_code == 200:
            logger.info(f"✅ Вебхук настроен: {webhook_url}")
            return f"✅ Вебхук настроен: {webhook_url}\nПодписка: {payload}"
        else:
            logger.error(f"❌ Ошибка: {r.status_code} - {r.text}")
            return f"❌ Ошибка: {r.status_code} - {r.text}"
            
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return f"❌ Ошибка: {e}"


@app.route('/report/<int:user_id>')
@safe_response
def report_page(user_id):
    report_path = report_gen.generate_report(user_id)
    if not report_path:
        return "❌ Нет данных для отчета", 404
    
    filename = os.path.basename(report_path)
    # Экранируем filename для безопасности
    safe_filename = escape(filename)
    download_url = f"/download_report/{user_id}/{safe_filename}"
    
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
@safe_response
def download_report(user_id, filename):
    try:
        # Проверяем, что filename безопасен
        if '..' in filename or '/' in filename or '\\' in filename:
            abort(400, "Некорректное имя файла")
        
        user_folder = fm.get_user_folder(user_id)
        file_path = os.path.join(user_folder, filename)
        
        if not os.path.exists(file_path):
            abort(404, "Файл не найден")
        
        report_gen.mark_report_downloaded(user_id)
        return send_file(file_path, as_attachment=True, download_name=filename, conditional=True)
        
    except Exception as e:
        logger.error(f"❌ Ошибка скачивания: {e}")
        abort(500, "Ошибка скачивания файла")


@app.route('/health')
def health():
    return {"status": "ok", "timestamp": time.time()}


@app.route('/status')
def status():
    return {"status": "running", "token_set": bool(TOKEN)}


@app.route('/report_status/<int:user_id>')
@safe_response
def report_status(user_id):
    try:
        stats = db.get_stats(user_id)
        pending = stats.get('pending', 0)
        success = stats.get('success', 0)
        failed = stats.get('errors', 0)
        total = stats.get('total', 0)
        ready = pending == 0 and success > 0
        
        return jsonify({
            'total': total,
            'pending': pending,
            'success': success,
            'failed': failed,
            'ready': ready,
            'message': '✅ Отчет готов!' if ready else f'⏳ Ожидание {pending} публикаций...'
        })
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({'error': 'Ошибка получения статуса'}), 500


@app.route('/force_report/<int:user_id>', methods=['POST'])
@safe_response
def force_report(user_id):
    """Принудительное создание отчета для пользователя"""
    try:
        report_path = report_gen.generate_report(user_id)
        if report_path:
            filename = os.path.basename(report_path)
            download_url = f"/download_report/{user_id}/{filename}"
            return jsonify({
                'success': True,
                'message': 'Отчет создан',
                'report_url': download_url
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Нет данных для отчета'
            }), 404
    except Exception as e:
        logger.error(f"❌ Ошибка создания отчета: {e}")
        return jsonify({
            'success': False,
            'message': 'Ошибка создания отчета'
        }), 500


@app.route('/force_update_links', methods=['POST'])
@safe_response
def force_update_links():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        if not user_id:
            return jsonify({'success': False, 'message': 'Нет user_id'}), 400
        
        publications = db.get_publications_with_status(user_id, 'pending')
        if not publications:
            return jsonify({'success': True, 'message': 'Нет pending публикаций'})
        
        updated = 0
        for pub in publications:
            folder_name = pub.get('folder_name')
            metadata = db.get_ad_metadata(user_id, folder_name)
            post_link = metadata.get('post_link')
            if post_link:
                db.update_publication_status(user_id, folder_name, 'success')
                updated += 1
        
        return jsonify({'success': True, 'message': f'Обновлено {updated} публикаций', 'updated': updated})
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({'success': False, 'message': 'Ошибка обновления'}), 500


@app.route('/clear_user_data/<int:user_id>', methods=['POST'])
@safe_response
def clear_user_data(user_id):
    try:
        db.clear_user_data(user_id)
        publisher.clear_diagnostic_log()
        publisher.pending_messages = {}
        logger.info(f"🗑️ Данные {user_id} очищены")
        return jsonify({'success': True, 'message': f'Данные {user_id} очищены'})
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({'success': False, 'message': 'Ошибка очистки'}), 500


@app.route('/auto_cleanup/<int:user_id>', methods=['POST'])
@safe_response
def auto_cleanup(user_id):
    try:
        def delayed_cleanup():
            time.sleep(300)
            logger.info(f"🧹 Автоочистка {user_id}")
            db.clear_user_data(user_id)
            user_folder = fm.get_user_folder(user_id)
            if os.path.exists(user_folder):
                for item in os.listdir(user_folder):
                    item_path = os.path.join(user_folder, item)
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                    elif not item.startswith('Отчет_'):
                        try:
                            os.remove(item_path)
                        except:
                            pass
            publisher.clear_diagnostic_log()
            publisher.pending_messages = {}
            publication_state.reset()
        
        threading.Thread(target=delayed_cleanup, daemon=True).start()
        return jsonify({'success': True, 'message': 'Автоочистка через 5 минут'})
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({'success': False, 'message': 'Ошибка'}), 500


@app.route('/cleanup_temp', methods=['POST'])
@safe_response
def cleanup_temp():
    try:
        temp_dir = os.path.join(DATA_DIR, 'temp')
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            os.makedirs(temp_dir, exist_ok=True)
            return jsonify({'success': True, 'message': 'Временные файлы очищены'})
        return jsonify({'success': True, 'message': 'Нет временных файлов'})
    except Exception as e:
        return jsonify({'success': False, 'message': 'Ошибка очистки'}), 500


@app.route('/webhook_test', methods=['GET'])
@safe_response
def webhook_test():
    return jsonify({
        'status': 'ok',
        'pending_count': len(publisher.pending_messages),
        'pending_keys': list(publisher.pending_messages.keys())
    })


@app.route('/diagnostic/<int:user_id>')
@safe_response
def diagnostic_log(user_id):
    try:
        diagnostic_data = publisher.get_diagnostic_log()
        return jsonify({
            'user_id': user_id,
            'total_entries': len(diagnostic_data),
            'diagnostic': diagnostic_data[-50:]
        })
    except Exception as e:
        return jsonify({'error': 'Ошибка получения диагностики'}), 500


@app.route('/diagnostic/clear', methods=['POST'])
@safe_response
def clear_diagnostic_log():
    publisher.clear_diagnostic_log()
    return jsonify({'success': True, 'message': 'Диагностика очищена'})


@app.route('/diagnostic/last')
@safe_response
def diagnostic_last():
    diagnostic_data = publisher.get_diagnostic_log()
    return jsonify({
        'success': True,
        'last_entry': diagnostic_data[-1] if diagnostic_data else None
    })


@app.errorhandler(ClientDisconnected)
def handle_client_disconnected(e):
    logger.warning(f"⚠️ Клиент разорвал соединение: {e}")
    return jsonify({'success': False, 'message': 'Соединение прервано'}), 400


@app.errorhandler(404)
def handle_not_found(e):
    return jsonify({'success': False, 'message': 'Ресурс не найден'}), 404


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return jsonify({'success': False, 'message': 'Метод не разрешен'}), 405


@app.errorhandler(Exception)
def handle_all_exceptions(error):
    logger.error(f"Критическая ошибка: {error}", exc_info=True)
    # В продакшене не показываем детали
    if os.environ.get("ENVIRONMENT") == "production":
        return jsonify({
            'success': False,
            'message': 'Внутренняя ошибка сервера'
        }), 500
    else:
        return jsonify({
            'success': False,
            'message': str(error)
        }), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    
    if TOKEN:
        logger.info(f"✅ Токен найден (первые 10): {TOKEN[:10]}...")
        
        webhook_url = os.environ.get("WEBHOOK_URL")
        if not webhook_url:
            webhook_url = "https://maxbot.bothost.tech"
            logger.warning("⚠️ WEBHOOK_URL не задан, использую значение по умолчанию")
        
        logger.info(f"🔗 Настройка вебхука на: {webhook_url}")
        
        try:
            headers = {"Authorization": TOKEN, "Content-Type": "application/json"}
            payload = {
                "url": webhook_url,
                "update_types": ["message_created", "bot_started", "bot_stopped"]
            }
            
            r = requests.post(
                "https://platform-api2.max.ru/subscriptions",
                headers=headers,
                json=payload,
                timeout=10,
                verify=False if os.environ.get("ENVIRONMENT") == "production" else True
            )
            
            if r.status_code == 200:
                logger.info(f"✅ Вебхук настроен при запуске: {webhook_url}")
            else:
                logger.warning(f"⚠️ Не удалось настроить вебхук: {r.status_code} - {r.text}")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка настройки вебхука: {e}")
    else:
        logger.error("❌ Токен не найден!")
    
    app.run(host='0.0.0.0', port=port, threaded=True)
