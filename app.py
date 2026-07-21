# app.py
from flask import Flask, request, jsonify, render_template_string, send_file
import requests
import logging
import os
import shutil
import urllib3
import json
import threading
import time
import base64
import signal
import sys
from werkzeug.exceptions import ClientDisconnected
from modules import Database, FileManager, Publisher, ReportGenerator

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("MAX_TOKEN") or os.environ.get("MAX_BOT_TOKEN") or os.environ.get("TOKEN")
BASE_URL = "https://platform-api2.max.ru"
DATA_DIR = "/app/data"

if not TOKEN:
    logger.error("❌ ТОКЕН НЕ НАЙДЕН!")

db = Database()
db.fix_publication_times()

fm = FileManager(DATA_DIR)

# ========== СОСТОЯНИЕ ПУБЛИКАЦИИ ==========
publication_state = {
    'is_paused': False,
    'is_running': False,
    'current_index': 0,
    'total_folders': 0,
    'folder_names': [],
    'folders_data': {},
    'results': [],
    'user_id': None,
    'delay': 30
}

# ========== ТАЙМАУТЫ ДЛЯ ЗАПРОСОВ ==========
@app.before_request
def before_request():
    request.start_time = time.time()

@app.after_request
def after_request(response):
    if hasattr(request, 'start_time'):
        elapsed = time.time() - request.start_time
        if elapsed > 25:
            logger.warning(f"⚠️ Медленный запрос: {elapsed:.2f}с")
    return response


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
                    verify=False
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
                verify=False
            )
            if response.status_code == 200:
                return True
            else:
                logger.error(f"❌ Ошибка отправки в чат: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logger.error(f"❌ Ошибка отправки в чат: {e}")
            return False

    def send_message_with_attachments(self, chat_id, text, tokens):
        if not self.token:
            return False
        try:
            attachments = []
            for token in tokens[:10]:
                attachments.append({
                    "type": "image",
                    "payload": {"token": token}
                })
            
            payload = {
                "chat_id": chat_id,
                "text": text,
                "format": "markdown",
                "attachments": attachments
            }
            
            response = requests.post(
                f"{self.base_url}/messages",
                headers={"Authorization": self.token, "Content-Type": "application/json"},
                json=payload,
                timeout=60,
                verify=False
            )
            
            if response.status_code == 200:
                logger.info(f"✅ Сообщение с фото отправлено в чат {chat_id}")
                return True
            else:
                logger.error(f"❌ Ошибка: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
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
                    verify=False
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
                    verify=False
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
                
            except requests.exceptions.Timeout:
                logger.error(f"⏰ Таймаут, попытка {attempt+1}")
                time.sleep(2)
            except requests.exceptions.ConnectionError:
                logger.error(f"🔌 Ошибка соединения, попытка {attempt+1}")
                time.sleep(2)
            except Exception as e:
                logger.error(f"❌ Ошибка: {e}, попытка {attempt+1}")
                time.sleep(2)
        
        return None


api = APIClient()
publisher = Publisher(api, fm, db)
report_gen = ReportGenerator(fm, db)

# ========== HTML СТРАНИЦА ==========
UPLOAD_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Загрузка объявлений в MAX</title>
    <style>
        body { font-family: Arial; max-width: 950px; margin: 50px auto; padding: 20px; background: #f5f5f5; }
        .container { background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1 { color: #333; margin-top: 0; display: flex; align-items: center; gap: 10px; }
        .drop-zone { border: 2px dashed #007bff; padding: 40px; margin: 20px 0; border-radius: 10px; background: #f8f9fa; text-align: center; cursor: pointer; transition: all 0.3s; }
        .drop-zone:hover { background: #e3f2fd; }
        .drop-zone.dragover { background: #d4edda; border-color: #28a745; }
        .drop-zone p { margin: 0; color: #666; }
        .drop-zone .icon { font-size: 48px; display: block; margin-bottom: 10px; }
        input[type="file"] { display: none; }
        .btn { padding: 12px 25px; border: none; border-radius: 5px; cursor: pointer; font-size: 15px; font-weight: bold; transition: all 0.3s; }
        .btn-success { background: #28a745; color: white; }
        .btn-success:hover { background: #218838; }
        .btn-danger { background: #dc3545; color: white; }
        .btn-danger:hover { background: #c82333; }
        .btn-pause { background: #ffc107; color: #333; }
        .btn-pause:hover { background: #e0a800; }
        .btn-resume { background: #17a2b8; color: white; }
        .btn-resume:hover { background: #138496; }
        .btn-stop { background: #dc3545; color: white; }
        .btn-stop:hover { background: #c82333; }
        .btn-primary { background: #007bff; color: white; }
        .btn-primary:hover { background: #0056b3; }
        .btn-info { background: #6c757d; color: white; }
        .btn-info:hover { background: #5a6268; }
        .btn-warning { background: #ffc107; color: #333; }
        .btn-warning:hover { background: #e0a800; }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .control-panel { background: #f8f9fa; padding: 15px; border-radius: 8px; margin: 15px 0; border: 1px solid #dee2e6; }
        .status-badge { display: inline-block; padding: 3px 12px; border-radius: 20px; font-size: 13px; font-weight: bold; }
        .status-badge.idle { background: #6c757d; color: white; }
        .status-badge.running { background: #28a745; color: white; }
        .status-badge.paused { background: #ffc107; color: #333; }
        .status-badge.stopped { background: #dc3545; color: white; }
        .progress-bar { width: 100%; height: 25px; background: #e9ecef; border-radius: 10px; overflow: hidden; margin: 10px 0; display: none; }
        .progress-bar .progress { height: 100%; background: #28a745; transition: width 0.3s; width: 0%; display: flex; align-items: center; justify-content: center; color: white; font-size: 12px; font-weight: bold; }
        .progress-bar .progress.paused { background: #ffc107; }
        .progress-bar .progress.stopped { background: #dc3545; }
        #log { background: #1e1e1e; color: #d4d4d4; padding: 15px; border-radius: 5px; font-family: 'Courier New', monospace; font-size: 12px; max-height: 350px; overflow-y: auto; margin: 20px 0; display: none; white-space: pre-wrap; line-height: 1.5; }
        .instructions { background: #fff3cd; padding: 15px 20px; border-radius: 5px; margin: 20px 0; border-left: 4px solid #ffc107; font-size: 14px; line-height: 1.6; }
        .instructions code { background: #f8f9fa; padding: 2px 8px; border-radius: 3px; font-size: 13px; color: #d63384; }
        .delay-container { margin: 15px 0; padding: 15px; background: #f0f8ff; border-radius: 8px; display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
        .delay-container label { font-weight: bold; }
        .delay-container input[type="range"] { width: 200px; margin: 0 10px; }
        .delay-container .delay-value { font-weight: bold; color: #007bff; min-width: 60px; }
        .delay-container .delay-hint { font-size: 12px; color: #666; }
        .button-group { display: flex; gap: 10px; flex-wrap: wrap; margin: 10px 0; }
        .file-list { text-align: left; margin: 10px 0; padding: 0; list-style: none; max-height: 300px; overflow-y: auto; }
        .file-list li { background: #f8f9fa; padding: 10px 15px; margin: 5px 0; border-radius: 5px; border-left: 3px solid #007bff; display: flex; justify-content: space-between; align-items: center; }
        .file-list li .count { background: #007bff; color: white; padding: 2px 10px; border-radius: 20px; font-size: 12px; }
        .selected-info { background: #e7f5ff; padding: 10px 15px; border-radius: 5px; margin: 10px 0; border-left: 3px solid #007bff; }
        .status { margin-top: 20px; padding: 15px; border-radius: 5px; display: none; }
        .status.success { background: #d4edda; color: #155724; display: block; border-left: 4px solid #28a745; }
        .status.error { background: #f8d7da; color: #721c24; display: block; border-left: 4px solid #dc3545; }
        .status.info { background: #d1ecf1; color: #0c5460; display: block; border-left: 4px solid #17a2b8; }
        .status.warning { background: #fff3cd; color: #856404; display: block; border-left: 4px solid #ffc107; }
        .status.stop { background: #f8d7da; color: #721c24; display: block; border-left: 4px solid #dc3545; }
        .report-section { margin-top: 20px; padding: 20px; background: #f8f9fa; border-radius: 10px; border: 1px solid #dee2e6; text-align: center; }
        #reportStatus { margin-top: 10px; padding: 10px; border-radius: 5px; display: none; font-weight: 500; white-space: pre-line; }
        .footer { text-align: center; margin-top: 30px; color: #999; font-size: 14px; border-top: 1px solid #eee; padding-top: 20px; }
        .queue-info { background: #e7f5ff; padding: 10px 15px; border-radius: 5px; margin: 10px 0; border-left: 3px solid #007bff; display: none; font-weight: 500; }
        .instruction-block { background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 15px 0; border-left: 4px solid #007bff; }
        .instruction-block h3 { margin-top: 0; color: #007bff; }
        .instruction-block ul { margin: 10px 0; padding-left: 20px; }
        .instruction-block li { margin: 5px 0; }
        @media (max-width: 600px) {
            body { padding: 10px; }
            .container { padding: 15px; }
            .button-group { flex-direction: column; }
            .btn { width: 100%; }
            .delay-container { flex-direction: column; align-items: stretch; }
            .delay-container input[type="range"] { width: 100%; }
        }
    </style>
</head>
<body>
<div class="container">
    <h1>📤 Загрузка объявлений в MAX</h1>
    
    <!-- ИНСТРУКЦИЯ ПО УПРАВЛЕНИЮ -->
    <div class="instruction-block">
        <h3>🎮 Управление публикацией</h3>
        <ul>
            <li><strong>⏸ Пауза</strong> — бот закончит текущую публикацию и остановится. Данные сохранены.</li>
            <li><strong>▶ Продолжить</strong> — бот продолжит со следующей папки после остановленной.</li>
            <li><strong>⏹ Стоп</strong> — бот завершает работу и <strong>создаёт отчёт</strong> по уже опубликованному.</li>
            <li><strong>📊 Скачать отчёт</strong> — доступен после остановки или завершения всех публикаций.</li>
        </ul>
    </div>
    
    <div class="instructions">
        <strong>📌 Как подготовить папку:</strong><br>
        1️⃣ Создайте головную папку (любое название)<br>
        2️⃣ Внутри создайте подпапки объявлений: <code>1 -123456789</code>, <code>2 -987654321</code><br>
        3️⃣ В каждой подпапке: <code>info.txt</code> (текст) и фото (1-10 шт)<br>
        4️⃣ В тексте используйте разделитель <code>#изъятая</code>:<br>
        &nbsp;&nbsp;• Текст ДО разделителя — публикуется в чат<br>
        &nbsp;&nbsp;• Текст ПОСЛЕ разделителя — идет в отчет<br>
        5️⃣ Перетащите головную папку в поле ниже<br>
        6️⃣ Каждая папка отправляется отдельным запросом<br>
        7️⃣ <strong>Максимум 10 фото</strong>
    </div>
    
    <!-- DROP ZONE -->
    <div class="drop-zone" id="dropZone">
        <span class="icon">📂</span>
        <p><strong>Перетащите головную папку сюда</strong></p>
        <p style="font-size: 14px; color: #888;">или</p>
        <button class="btn btn-primary" onclick="document.getElementById('folderInput').click()">Выбрать папку</button>
        <input type="file" id="folderInput" webkitdirectory multiple>
    </div>
    
    <!-- СПИСОК ФАЙЛОВ -->
    <div id="fileList" style="display:none;">
        <div class="selected-info" id="selectedInfo"></div>
        <ul class="file-list" id="fileListContent"></ul>
    </div>
    
    <!-- ЗАДЕРЖКА -->
    <div class="delay-container" id="delayContainer" style="display:none;">
        <label for="delaySlider">⏱️ Задержка между объявлениями:</label>
        <input type="range" id="delaySlider" min="30" max="120" value="30" 
               oninput="document.getElementById('delayValue').textContent = this.value + ' сек'">
        <span class="delay-value" id="delayValue">30 сек</span>
        <span class="delay-hint">(30 сек – 2 минуты)</span>
    </div>
    
    <!-- УПРАВЛЕНИЕ -->
    <div class="control-panel" id="controlPanel" style="display:none;">
        <div class="button-group">
            <button class="btn btn-success" onclick="uploadFolder()" id="btnUpload">🚀 Загрузить</button>
            <button class="btn btn-pause" onclick="pausePublication()" id="btnPause" style="display:none;">⏸ Пауза</button>
            <button class="btn btn-resume" onclick="resumePublication()" id="btnResume" style="display:none;">▶ Продолжить</button>
            <button class="btn btn-stop" onclick="stopPublication()" id="btnStop" style="display:none;">⏹ Стоп</button>
            <button class="btn btn-danger" onclick="clearFiles()" id="btnClear">🗑️ Очистить список</button>
            <button class="btn btn-danger" onclick="clearAllData()" id="btnClearDB">🗑️ Очистить БД</button>
        </div>
        <div style="margin-top: 10px; font-size: 14px;">
            <span>Статус: </span>
            <span id="publicationStatus" class="status-badge idle">Ожидание</span>
            <span style="margin-left: 15px;" id="progressText"></span>
        </div>
    </div>
    
    <!-- ПРОГРЕСС -->
    <div class="progress-bar" id="progressBar">
        <div class="progress" id="progress">0%</div>
    </div>
    
    <div id="status" class="status"></div>
    <div id="log"></div>
    
    <!-- ОТЧЁТЫ -->
    <div class="report-section">
        <div class="button-group" style="justify-content: center;">
            <button class="btn btn-primary" id="reportBtn" onclick="getReport()" disabled>📊 Скачать отчет</button>
            <button class="btn btn-info" onclick="checkReportStatus()">🔄 Проверить статус</button>
            <button class="btn btn-warning" onclick="forceUpdateLinks()">🔄 Обновить ссылки</button>
            <button class="btn btn-success" onclick="setupWebhook()">🔗 Настроить вебхук</button>
        </div>
        <div id="reportStatus" style="margin-top: 10px; padding: 10px; border-radius: 5px; display: none;"></div>
        <p style="margin-top: 10px; color: #666; font-size: 14px;">После публикации подождите 1-2 минуты, затем нажмите "Проверить статус"</p>
    </div>
    
    <div class="footer">⚡ MAX Bot | Загрузка объявлений v3.0 | Пауза, Стоп, Отчёт</div>
</div>

<script>
    // ===== КОНСТАНТЫ =====
    const userId = 151296248;
    let selectedFiles = [];
    let isProcessing = false;
    let isPaused = false;
    let isStopped = false;
    let reportReady = false;
    let statusCheckInterval = null;
    
    // ===== ЭЛЕМЕНТЫ =====
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
    const btnClearDB = document.getElementById('btnClearDB');
    const delaySlider = document.getElementById('delaySlider');
    
    // ===== DROP ZONE =====
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
            if (parts.length >= 2) {
                const folder = parts[0] + '/' + parts[1];
                folders.add(folder);
                if (!fileCount[folder]) fileCount[folder] = 0;
                fileCount[folder]++;
            }
        });
        const sortedFolders = Array.from(folders).sort();
        sortedFolders.forEach(folder => {
            const li = document.createElement('li');
            const count = fileCount[folder] || 0;
            const displayName = folder.includes('/') ? folder.split('/')[1] : folder;
            li.innerHTML = `<span>📁 <strong>${displayName}</strong></span><span class="count">${count} файлов</span>`;
            fileListContent.appendChild(li);
        });
        selectedInfo.textContent = `✅ Выбрано ${sortedFolders.length} папок, всего ${files.length} файлов`;
        fileList.style.display = 'block';
        delayContainer.style.display = 'block';
        controlPanel.style.display = 'block';
        btnUpload.disabled = false;
        showStatus('info', '📦 Выберите папку и нажмите "Загрузить"');
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
        publicationStatus.textContent = '⏸ Ожидание';
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
    
    // ===== ПАУЗА =====
    async function pausePublication() {
        try {
            const response = await fetch('/pause_publication', { method: 'POST', headers: { 'Content-Type': 'application/json' } });
            const result = await response.json();
            if (result.success) {
                showStatus('info', '⏸ Публикация на паузе');
                addLog('⏸ ПАУЗА');
                isPaused = true;
                btnPause.style.display = 'none';
                btnResume.style.display = 'inline-block';
                publicationStatus.className = 'status-badge paused';
                publicationStatus.textContent = '⏸ На паузе';
                progress.className = 'progress paused';
            } else {
                showStatus('error', '❌ ' + result.message);
            }
        } catch (error) {
            showStatus('error', '❌ ' + error.message);
        }
    }
    
    // ===== ПРОДОЛЖИТЬ =====
    async function resumePublication() {
        try {
            const response = await fetch('/resume_publication', { method: 'POST', headers: { 'Content-Type': 'application/json' } });
            const result = await response.json();
            if (result.success) {
                showStatus('info', '▶ Публикация продолжена');
                addLog('▶ ПРОДОЛЖЕНИЕ');
                isPaused = false;
                btnPause.style.display = 'inline-block';
                btnResume.style.display = 'none';
                publicationStatus.className = 'status-badge running';
                publicationStatus.textContent = '▶ Выполняется';
                progress.className = 'progress';
                uploadFolder();
            } else {
                showStatus('error', '❌ ' + result.message);
            }
        } catch (error) {
            showStatus('error', '❌ ' + error.message);
        }
    }
    
    // ===== СТОП =====
    async function stopPublication() {
        if (!confirm('⏹ Остановить публикацию и создать отчёт?')) return;
        try {
            const response = await fetch('/stop_publication', { method: 'POST', headers: { 'Content-Type': 'application/json' } });
            const result = await response.json();
            if (result.success) {
                showStatus('stop', '⏹ Публикация остановлена, отчёт готов');
                addLog('⏹ СТОП: отчёт создан');
                btnPause.style.display = 'none';
                btnResume.style.display = 'none';
                btnStop.style.display = 'none';
                btnUpload.disabled = false;
                btnClear.disabled = false;
                btnClearDB.disabled = false;
                reportBtn.disabled = false;
                reportReady = true;
                publicationStatus.className = 'status-badge stopped';
                publicationStatus.textContent = '⏹ Остановлено';
                progress.className = 'progress stopped';
                if (result.report_url) addLog('📊 Отчёт: ' + result.report_url);
            } else {
                showStatus('error', '❌ ' + result.message);
            }
        } catch (error) {
            showStatus('error', '❌ ' + error.message);
        }
    }
    
    // ===== ЗАГРУЗКА ПАПКИ =====
    async function uploadFolder() {
        if (selectedFiles.length === 0) {
            showStatus('error', '❌ Выберите папку');
            return;
        }
        
        // Проверяем статус
        try {
            const statusResponse = await fetch('/publication_status');
            const statusData = await statusResponse.json();
            if (statusData.is_running && !statusData.is_paused) {
                showStatus('warning', '⚠️ Публикация уже выполняется');
                return;
            }
            if (statusData.is_paused) {
                showStatus('info', '⏸ Публикация на паузе. Нажмите "Продолжить"');
                return;
            }
        } catch (e) {}
        
        isProcessing = true;
        isStopped = false;
        isPaused = false;
        btnUpload.disabled = true;
        btnClear.disabled = true;
        btnClearDB.disabled = true;
        btnPause.style.display = 'inline-block';
        btnStop.style.display = 'inline-block';
        btnResume.style.display = 'none';
        publicationStatus.className = 'status-badge running';
        publicationStatus.textContent = '▶ Выполняется';
        
        const delay = delaySlider ? parseInt(delaySlider.value) : 30;
        addLog(`⏱️ Задержка: ${delay} сек`);
        showStatus('info', '⏳ Подготовка...');
        progressBar.style.display = 'block';
        progress.style.width = '0%';
        progress.textContent = '0%';
        logDiv.textContent = '';
        addLog('🚀 Начинаем обработку...');
        
        const folders = {};
        selectedFiles.forEach(file => {
            const parts = file.webkitRelativePath.split('/');
            if (parts.length >= 2) {
                const folderName = parts[0] + '/' + parts[1];
                if (!folders[folderName]) folders[folderName] = [];
                folders[folderName].push(file);
            }
        });
        
        const folderNames = Object.keys(folders);
        const totalFolders = folderNames.length;
        addLog(`📁 Найдено ${totalFolders} папок`);
        
        let successCount = 0;
        let errorCount = 0;
        const results = [];
        
        for (let i = 0; i < folderNames.length; i++) {
            // Проверяем паузу
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
                    publicationStatus.textContent = '⏸ На паузе';
                    return;
                }
                if (!statusData.is_running) {
                    addLog('⏹ Остановлено');
                    break;
                }
            } catch (e) {}
            
            if (isStopped) break;
            
            const folderName = folderNames[i];
            const files = folders[folderName];
            const percent = Math.round((i / totalFolders) * 100);
            progress.style.width = percent + '%';
            progress.textContent = `${i}/${totalFolders}`;
            progressText.textContent = `📊 ${i}/${totalFolders} папок`;
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
            await new Promise(r => setTimeout(r, 2000));
        }
        
        progress.style.width = '100%';
        progress.textContent = `${totalFolders}/${totalFolders}`;
        progressText.textContent = `✅ ${totalFolders}/${totalFolders} папок`;
        showStatus('success', `✅ Загружено ${successCount} папок, ошибок: ${errorCount}`);
        addLog(`📊 Завершено: ${successCount} успешно, ${errorCount} ошибок`);
        
        btnUpload.disabled = false;
        btnClear.disabled = false;
        btnClearDB.disabled = false;
        btnPause.style.display = 'none';
        btnStop.style.display = 'none';
        isProcessing = false;
        publicationStatus.className = 'status-badge idle';
        publicationStatus.textContent = '⏸ Ожидание';
        
        setTimeout(() => { addLog('🔄 Проверка статуса...'); checkReportStatus(); }, 30000);
    }
    
    // ===== ПОДГОТОВКА ПАПКИ =====
    async function prepareFolderData(folderName, files) {
        const txtFile = files.find(f => f.name === 'info.txt' || f.name.endsWith('.txt'));
        if (!txtFile) return null;
        let fullText = await txtFile.text();
        let adText = fullText;
        let metadataText = '';
        if (fullText.includes('#изъятая')) {
            const parts = fullText.split('#изъятая');
            adText = parts[0].trim();
            metadataText = parts[1] ? parts[1].trim() : '';
        }
        const imageFiles = files.filter(f => f.type && f.type.startsWith('image/')).slice(0, 10);
        const imageTokens = [];
        for (const img of imageFiles) {
            if (isStopped) break;
            const token = await uploadSinglePhoto(img, folderName);
            if (token) imageTokens.push(token);
            await new Promise(r => setTimeout(r, 300));
        }
        return {
            folderName: folderName,
            adText: adText,
            metadataText: metadataText,
            fullText: fullText,
            imageTokens: imageTokens
        };
    }
    
    // ===== ЗАГРУЗКА ФОТО =====
    async function uploadSinglePhoto(file, folderName) {
        try {
            const formData = new FormData();
            formData.append('photo', file);
            formData.append('user_id', userId);
            formData.append('folder_name', folderName);
            const response = await fetch('/upload_photo', {
                method: 'POST',
                body: formData
            });
            const result = await response.json();
            if (result.success) {
                addLog(`✅ Фото ${file.name} загружено`);
                return result.token;
            }
            return null;
        } catch (error) {
            addLog(`❌ Ошибка фото ${file.name}`);
            return null;
        }
    }
    
    // ===== ОТЧЁТЫ =====
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
            } else if (result.success > 0) {
                text += '\n✅ Отчет готов!';
                reportStatus.className = 'status success';
                reportBtn.disabled = false;
                reportReady = true;
            } else {
                text += '\n⏳ Нет готовых публикаций';
                reportStatus.className = 'status info';
                reportBtn.disabled = true;
                reportReady = false;
            }
            reportStatus.textContent = text;
        } catch (error) {
            reportStatus.style.display = 'block';
            reportStatus.className = 'status error';
            reportStatus.textContent = '❌ ' + error.message;
        }
    }
    
    async function forceUpdateLinks() {
        try {
            addLog('🔄 Обновление ссылок...');
            const response = await fetch('/force_update_links', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: parseInt(userId) })
            });
            const result = await response.json();
            if (result.success) {
                addLog(`✅ ${result.message}`);
                showStatus('success', `✅ ${result.message}`);
                setTimeout(checkReportStatus, 1000);
            } else {
                addLog(`❌ ${result.message}`);
            }
        } catch (error) {
            addLog(`❌ ${error.message}`);
        }
    }
    
    async function clearAllData() {
        if (!confirm('⚠️ Удалить ВСЕ данные?')) return;
        try {
            const response = await fetch(`/clear_user_data/${userId}`, { method: 'POST' });
            const result = await response.json();
            if (result.success) {
                showStatus('success', '✅ Данные очищены');
                addLog('✅ Данные очищены');
                reportStatus.style.display = 'none';
                reportBtn.disabled = true;
                reportReady = false;
            }
        } catch (error) {
            showStatus('error', '❌ ' + error.message);
        }
    }
    
    // ===== ВЕБХУК =====
    async function setupWebhook() {
        try {
            const response = await fetch('/setup_webhook');
            const result = await response.text();
            showStatus('info', result);
        } catch (error) {
            showStatus('error', '❌ Ошибка настройки вебхука: ' + error.message);
        }
    }
</script>
</body>
</html>
"""

# ========== МАРШРУТЫ ==========

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        return webhook()
    return "🤖 MAX Bot is running! Webhook endpoint: /webhook"


@app.route('/upload', methods=['GET'])
def upload_page():
    return render_template_string(UPLOAD_PAGE)


@app.route('/upload_photo', methods=['POST'])
def upload_photo():
    try:
        photo = request.files.get('photo')
        user_id = request.form.get('user_id')
        folder_name = request.form.get('folder_name')
        
        if not photo:
            return jsonify({'success': False, 'message': 'Нет фото'}), 400
        if not user_id:
            return jsonify({'success': False, 'message': 'Нет user_id'}), 400
        
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
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/publish_folder', methods=['POST'])
def publish_folder():
    global publication_state
    
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        folder_data = data.get('folder')
        delay = data.get('delay', 30)
        delay = max(30, min(120, delay))
        
        if not user_id or not folder_data:
            return jsonify({'success': False, 'message': 'Нет данных'}), 400
        
        # Сохраняем состояние для паузы
        if not publication_state['is_running']:
            publication_state['is_running'] = True
            publication_state['is_paused'] = False
            publication_state['user_id'] = user_id
            publication_state['delay'] = delay
            publication_state['current_index'] = 0
            publication_state['total_folders'] = 0
            publication_state['results'] = []
        
        # Проверяем паузу
        if publication_state['is_paused']:
            return jsonify({'success': False, 'message': 'Публикация на паузе'}), 409
        
        folder_name = folder_data.get('folderName')
        ad_text = folder_data.get('adText')
        metadata_text = folder_data.get('metadataText')
        image_tokens = folder_data.get('imageTokens', [])
        
        logger.info(f"📦 Папка: {folder_name} от {user_id}, задержка: {delay}с")
        logger.info(f"📝 Текст: {len(ad_text)} символов, 🖼️ Фото: {len(image_tokens)}")
        
        success, message = publisher.publish_folder_with_tokens(
            user_id, folder_name, ad_text, metadata_text, image_tokens
        )
        
        # Обновляем состояние
        publication_state['current_index'] += 1
        publication_state['results'].append({
            'folder': folder_name,
            'success': success,
            'message': message
        })
        
        if delay > 0 and success:
            logger.info(f"⏱️ Задержка {delay} сек")
            time.sleep(delay)
        
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'message': message}), 500
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/pause_publication', methods=['POST'])
def pause_publication():
    global publication_state
    
    if not publication_state['is_running']:
        return jsonify({'success': False, 'message': 'Нет активной публикации'}), 400
    
    publication_state['is_paused'] = True
    logger.info(f"⏸ ПАУЗА: публикация остановлена для {publication_state['user_id']}")
    
    return jsonify({
        'success': True,
        'message': '⏸ Публикация на паузе',
        'current_index': publication_state.get('current_index', 0),
        'total': publication_state.get('total_folders', 0)
    })


@app.route('/resume_publication', methods=['POST'])
def resume_publication():
    global publication_state
    
    if not publication_state['is_paused']:
        return jsonify({'success': False, 'message': 'Публикация не на паузе'}), 400
    
    publication_state['is_paused'] = False
    logger.info(f"▶ ПРОДОЛЖЕНИЕ: публикация возобновлена для {publication_state['user_id']}")
    
    return jsonify({
        'success': True,
        'message': '▶ Публикация продолжена'
    })


@app.route('/stop_publication', methods=['POST'])
def stop_publication():
    global publication_state
    
    if not publication_state['is_running']:
        return jsonify({'success': False, 'message': 'Нет активной публикации'}), 400
    
    user_id = publication_state.get('user_id')
    
    # Останавливаем
    publication_state['is_running'] = False
    publication_state['is_paused'] = False
    
    logger.info(f"⏹ СТОП: публикация завершена для {user_id}")
    
    # Генерируем отчёт
    report_url = None
    if user_id:
        try:
            report_path = report_gen.generate_report(user_id)
            if report_path:
                filename = os.path.basename(report_path)
                report_url = f"https://maxbot.bothost.tech/download_report/{user_id}/{filename}"
                
                # Отправляем уведомление в телеграм
                api.send_message(
                    user_id,
                    f"⏹ **Публикация остановлена!**\n\n"
                    f"📊 Отчёт создан: [Скачать]({report_url})\n\n"
                    f"📦 Обработано: {publication_state.get('current_index', 0)} папок"
                )
        except Exception as e:
            logger.error(f"❌ Ошибка создания отчёта: {e}")
    
    return jsonify({
        'success': True,
        'message': '⏹ Публикация остановлена, отчёт создан',
        'report_url': report_url,
        'processed': publication_state.get('current_index', 0)
    })


@app.route('/publication_status', methods=['GET'])
def publication_status():
    global publication_state
    
    return jsonify({
        'is_running': publication_state['is_running'],
        'is_paused': publication_state['is_paused'],
        'current_index': publication_state.get('current_index', 0),
        'total_folders': publication_state.get('total_folders', 0),
        'user_id': publication_state.get('user_id'),
        'results_count': len(publication_state.get('results', []))
    })


@app.route('/webhook', methods=['GET', 'POST'])
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
            
            if chat_id is not None:
                chat_id = str(chat_id)
            
            logger.info(f"📨 chat_id: {chat_id}, user_id: {user_id}, text: {text}")
            
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
                    # Останавливаем публикацию через API
                    if publication_state['is_running']:
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
        
        if update_type == 'bot_stopped':
            logger.info("📨 Получено событие bot_stopped")
            return jsonify({"ok": True}), 200
        
        if update_type == 'bot_started':
            logger.info("📨 Получено событие bot_started")
            return jsonify({"ok": True}), 200
        
        logger.info(f"ℹ️ Вебхук с update_type: {update_type}")
        return jsonify({"ok": True}), 200
        
    except Exception as e:
        logger.error(f"❌ ОШИБКА В ВЕБХУКЕ: {e}")
        return jsonify({"ok": False}), 500


@app.route('/setup_webhook', methods=['GET', 'POST'])
def setup_webhook():
    token = request.args.get('token') or TOKEN
    if not token:
        return "❌ Токен не найден", 400
    
    webhook_url = os.environ.get("WEBHOOK_URL")
    if not webhook_url:
        webhook_url = "https://maxbot.bothost.tech"
        logger.warning("⚠️ WEBHOOK_URL не задан, использую значение по умолчанию")
    
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
            verify=False
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
        
        report_gen.mark_report_downloaded(user_id)
        return send_file(file_path, as_attachment=True, download_name=filename, conditional=True)
        
    except Exception as e:
        logger.error(f"❌ Ошибка скачивания: {e}")
        return str(e), 500


@app.route('/health')
def health():
    return {"status": "ok"}


@app.route('/status')
def status():
    return {"status": "running", "token_set": bool(TOKEN)}


@app.route('/report_status/<int:user_id>')
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
        return jsonify({'error': str(e)}), 500


@app.route('/force_update_links', methods=['POST'])
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
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/clear_user_data/<int:user_id>', methods=['POST'])
def clear_user_data(user_id):
    try:
        db.clear_user_data(user_id)
        publisher.clear_diagnostic_log()
        publisher.pending_messages = {}
        logger.info(f"🗑️ Данные {user_id} очищены")
        return jsonify({'success': True, 'message': f'Данные {user_id} очищены'})
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/auto_cleanup/<int:user_id>', methods=['POST'])
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
            global publication_state
            publication_state['is_running'] = False
            publication_state['is_paused'] = False
        
        threading.Thread(target=delayed_cleanup, daemon=True).start()
        return jsonify({'success': True, 'message': 'Автоочистка через 5 минут'})
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/cleanup_temp', methods=['POST'])
def cleanup_temp():
    try:
        temp_dir = os.path.join(DATA_DIR, 'temp')
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            os.makedirs(temp_dir, exist_ok=True)
            return jsonify({'success': True, 'message': 'Временные файлы очищены'})
        return jsonify({'success': True, 'message': 'Нет временных файлов'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/webhook_test', methods=['GET'])
def webhook_test():
    return jsonify({
        'status': 'ok',
        'pending_count': len(publisher.pending_messages),
        'pending_keys': list(publisher.pending_messages.keys())
    })


@app.route('/diagnostic/<int:user_id>')
def diagnostic_log(user_id):
    try:
        diagnostic_data = publisher.get_diagnostic_log()
        return jsonify({
            'user_id': user_id,
            'total_entries': len(diagnostic_data),
            'diagnostic': diagnostic_data[-50:]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/diagnostic/clear', methods=['POST'])
def clear_diagnostic_log():
    publisher.clear_diagnostic_log()
    return jsonify({'success': True, 'message': 'Диагностика очищена'})


@app.route('/diagnostic/last')
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


@app.errorhandler(Exception)
def handle_all_exceptions(error):
    logger.error(f"Критическая ошибка: {error}", exc_info=True)
    return jsonify({
        'success': False,
        'message': 'Внутренняя ошибка сервера',
        'details': str(error)
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
                verify=False
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
