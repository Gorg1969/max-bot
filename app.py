from flask import Flask, request, jsonify, render_template_string, send_file
import requests
import logging
import os
import shutil
import urllib3
import json
import threading
import time
from werkzeug.exceptions import ClientDisconnected
from modules import Database, FileManager, Publisher, WebInterface
from modules.report_generator import ReportGenerator
from modules.session_manager import SessionManager
from modules.diagnostics import Diagnostics

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("MAX_TOKEN") or os.environ.get("MAX_BOT_TOKEN") or os.environ.get("TOKEN")
BASE_URL = "https://platform-api2.max.ru"
DATA_DIR = "/app/data"

if not TOKEN:
    logger.error("❌ ТОКЕН НЕ НАЙДЕН!")

db = Database()
fm = FileManager(DATA_DIR)

# ========== НОВЫЙ МЕНЕДЖЕР СЕССИЙ ==========
session_manager = SessionManager(TOKEN, BASE_URL)

# ========== PUBLISHER С НОВЫМ МЕНЕДЖЕРОМ ==========
publisher = Publisher(session_manager, fm, db)

# ========== ДИАГНОСТИКА ==========
diagnostics = Diagnostics(DATA_DIR)

# ========== КЛАСС APIClient (ДОЛЖЕН БЫТЬ ДО ИСПОЛЬЗОВАНИЯ) ==========
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
            for token in tokens[:3]:
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

# ========== СОЗДАЕМ API ПОСЛЕ ОПРЕДЕЛЕНИЯ КЛАССА ==========
api = APIClient()

# ========== ОСТАЛЬНЫЕ КОМПОНЕНТЫ ==========
report_gen = ReportGenerator(fm, db)
web_interface = WebInterface(fm, publisher)

# ========== HTML СТРАНИЦА МУЛЬТИ-ЗАГРУЗКИ ==========
UPLOAD_PAGE_MULTI = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Загрузка объявлений</title>
    <style>
        * { box-sizing: border-box; }
        body { font-family: Arial, sans-serif; max-width: 1000px; margin: 0 auto; padding: 20px; background: #f0f2f5; }
        
        .container { background: white; padding: 30px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        
        h1 { color: #1a1a2e; margin-top: 0; display: flex; align-items: center; gap: 10px; }
        h1 small { font-size: 14px; color: #666; font-weight: normal; }
        
        .drop-zone {
            border: 2px dashed #4a90d9;
            padding: 40px;
            margin: 20px 0;
            border-radius: 10px;
            background: #f8f9fa;
            text-align: center;
            cursor: pointer;
            transition: all 0.3s;
        }
        .drop-zone:hover { background: #e3f2fd; }
        .drop-zone.dragover { background: #d4edda; border-color: #28a745; }
        .drop-zone .icon { font-size: 48px; display: block; margin-bottom: 10px; }
        .drop-zone .limit { font-size: 12px; color: #999; margin-top: 5px; }
        
        .folder-list {
            margin: 20px 0;
            padding: 0;
            list-style: none;
        }
        .folder-list li {
            background: #f8f9fa;
            padding: 12px 15px;
            margin: 5px 0;
            border-radius: 8px;
            border-left: 4px solid #4a90d9;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .folder-list li .badge {
            background: #4a90d9;
            color: white;
            padding: 2px 12px;
            border-radius: 20px;
            font-size: 12px;
        }
        .folder-list li .remove-btn {
            background: #dc3545;
            color: white;
            border: none;
            border-radius: 50%;
            width: 24px;
            height: 24px;
            cursor: pointer;
            font-size: 14px;
            line-height: 24px;
            text-align: center;
        }
        
        .settings-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin: 20px 0;
            padding: 20px;
            background: #f8f9fa;
            border-radius: 10px;
        }
        .settings-group label {
            display: block;
            font-weight: bold;
            margin-bottom: 5px;
            font-size: 14px;
            color: #333;
        }
        .settings-group input, .settings-group select {
            width: 100%;
            padding: 8px 12px;
            border: 1px solid #ddd;
            border-radius: 5px;
            font-size: 14px;
        }
        .settings-group small {
            display: block;
            color: #666;
            font-size: 12px;
            margin-top: 3px;
        }
        
        .btn {
            padding: 10px 25px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
            font-weight: bold;
            transition: all 0.3s;
        }
        .btn-primary { background: #4a90d9; color: white; }
        .btn-primary:hover { background: #357abd; }
        .btn-success { background: #28a745; color: white; }
        .btn-success:hover { background: #218838; }
        .btn-danger { background: #dc3545; color: white; }
        .btn-danger:hover { background: #c82333; }
        .btn-secondary { background: #6c757d; color: white; }
        .btn-secondary:hover { background: #5a6268; }
        
        .button-group { display: flex; gap: 10px; flex-wrap: wrap; margin: 15px 0; }
        
        .status {
            margin-top: 15px;
            padding: 15px;
            border-radius: 5px;
            display: none;
        }
        .status.success { background: #d4edda; color: #155724; display: block; border-left: 4px solid #28a745; }
        .status.error { background: #f8d7da; color: #721c24; display: block; border-left: 4px solid #dc3545; }
        .status.info { background: #d1ecf1; color: #0c5460; display: block; border-left: 4px solid #17a2b8; }
        .status.warning { background: #fff3cd; color: #856404; display: block; border-left: 4px solid #ffc107; }
        
        .progress-bar {
            width: 100%;
            height: 25px;
            background: #e9ecef;
            border-radius: 10px;
            overflow: hidden;
            margin: 10px 0;
            display: none;
        }
        .progress-bar .progress {
            height: 100%;
            background: linear-gradient(90deg, #28a745, #20c997);
            transition: width 0.3s;
            width: 0%;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-size: 12px;
            font-weight: bold;
        }
        
        #log {
            background: #1e1e1e;
            color: #d4d4d4;
            padding: 15px;
            border-radius: 5px;
            font-family: 'Courier New', monospace;
            font-size: 12px;
            max-height: 300px;
            overflow-y: auto;
            margin: 15px 0;
            display: none;
            white-space: pre-wrap;
            line-height: 1.5;
        }
        #log .success { color: #4caf50; }
        #log .error { color: #f44336; }
        #log .warning { color: #ff9800; }
        #log .info { color: #2196f3; }
        
        .instructions {
            background: #e7f5ff;
            padding: 15px 20px;
            border-radius: 8px;
            margin: 15px 0;
            border-left: 4px solid #4a90d9;
        }
        .instructions code {
            background: #f8f9fa;
            padding: 2px 8px;
            border-radius: 3px;
            font-size: 13px;
            color: #d63384;
        }
        
        .report-section {
            margin-top: 20px;
            padding: 20px;
            background: #f8f9fa;
            border-radius: 10px;
            border: 1px solid #dee2e6;
            text-align: center;
        }
        
        .footer {
            text-align: center;
            margin-top: 30px;
            color: #999;
            font-size: 14px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>📤 Загрузка объявлений <small>MAX Bot v2.0</small></h1>
        
        <div class="instructions">
            <strong>📌 Как подготовить папки:</strong><br>
            1️⃣ Создайте папки с объявлениями (можно до 5 корневых папок)<br>
            2️⃣ Внутри каждой: подпапки вида <code>Название -123456789</code><br>
            3️⃣ В каждой подпапке: <code>info.txt</code> (текст) и фото (до 10 шт)<br>
            4️⃣ Используйте разделитель <code>#изъятая</code> для метаданных<br>
            5️⃣ Перетащите папки в поле ниже или выберите через диалог<br>
            6️⃣ Настройте параметры публикации и нажмите "Загрузить"
        </div>
        
        <!-- Зона загрузки -->
        <div class="drop-zone" id="dropZone">
            <span class="icon">📂</span>
            <p><strong>Перетащите папки сюда</strong></p>
            <p style="color: #666; font-size: 14px;">или</p>
            <button class="btn btn-primary" onclick="document.getElementById('folderInput').click()">Выбрать папки</button>
            <input type="file" id="folderInput" webkitdirectory multiple>
            <div class="limit">Максимум 5 корневых папок</div>
        </div>
        
        <!-- Список папок -->
        <div id="folderList" style="display:none;">
            <h3>📁 Выбранные папки:</h3>
            <ul class="folder-list" id="folderListContent"></ul>
            <div class="button-group">
                <button class="btn btn-secondary" onclick="clearFolders()">🗑️ Очистить все</button>
            </div>
        </div>
        
        <!-- Настройки -->
        <div class="settings-grid">
            <div class="settings-group">
                <label>⏱️ Задержка между сообщениями (сек)</label>
                <input type="number" id="delay" value="180" min="10" max="600">
                <small>Рекомендуется: 120-300 сек</small>
            </div>
            
            <div class="settings-group">
                <label>📋 Порядок публикации</label>
                <select id="order">
                    <option value="sequential">По порядку (папка за папкой)</option>
                    <option value="shuffle">Случайный (перемешать все)</option>
                    <option value="round_robin">Круговой (по одному из каждой)</option>
                </select>
                <small>Как публиковать объявления из разных папок</small>
            </div>
            
            <div class="settings-group">
                <label>📷 Максимум фото на объявление</label>
                <input type="number" id="maxPhotos" value="3" min="1" max="10">
                <small>Сколько фото прикреплять к сообщению</small>
            </div>
            
            <div class="settings-group">
                <label>⏹️ При ошибке</label>
                <select id="onError">
                    <option value="continue">Продолжить со следующим</option>
                    <option value="stop">Остановить публикацию</option>
                    <option value="retry">Повторить (3 раза)</option>
                </select>
                <small>Что делать при ошибке отправки</small>
            </div>
        </div>
        
        <div class="button-group">
            <button class="btn btn-success" onclick="uploadFolders()" id="uploadBtn">🚀 Загрузить</button>
            <button class="btn btn-danger" onclick="stopPublish()" id="stopBtn" style="display:none;">⏹️ Остановить</button>
        </div>
        
        <div class="progress-bar" id="progressBar">
            <div class="progress" id="progress">0%</div>
        </div>
        
        <div id="status" class="status"></div>
        <div id="log"></div>
        
        <div class="report-section">
            <button class="btn btn-primary" onclick="getReport()">📊 Скачать отчет</button>
            <button class="btn btn-secondary" onclick="getDiagnostics()">🔍 Диагностика</button>
            <p style="margin-top: 10px; color: #666; font-size: 14px;">После завершения публикации</p>
        </div>
        
        <div class="footer">⚡ MAX Bot v2.0 | Мульти-загрузка объявлений</div>
    </div>

    <script>
        const urlParams = new URLSearchParams(window.location.search);
        const userId = parseInt(urlParams.get('user_id')) || 151296248;
        
        let selectedFolders = {};
        let isProcessing = false;
        let isStopped = false;
        
        // DOM элементы
        const dropZone = document.getElementById('dropZone');
        const folderInput = document.getElementById('folderInput');
        const folderList = document.getElementById('folderList');
        const folderListContent = document.getElementById('folderListContent');
        const statusDiv = document.getElementById('status');
        const logDiv = document.getElementById('log');
        const progressBar = document.getElementById('progressBar');
        const progress = document.getElementById('progress');
        const uploadBtn = document.getElementById('uploadBtn');
        const stopBtn = document.getElementById('stopBtn');
        
        // Drag & Drop
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
            const folders = {};
            
            for (let item of items) {
                if (item.kind === 'file') {
                    const entry = item.webkitGetAsEntry();
                    if (entry && entry.isDirectory) {
                        const folderName = entry.name;
                        if (!folders[folderName]) {
                            folders[folderName] = [];
                        }
                        readDirectory(entry, folders[folderName], folderName + '/');
                    }
                }
            }
            
            addFolders(folders);
        });
        
        folderInput.addEventListener('change', (e) => {
            const files = Array.from(e.target.files);
            if (files.length === 0) return;
            
            const folders = {};
            files.forEach(file => {
                const pathParts = file.webkitRelativePath.split('/');
                if (pathParts.length >= 1) {
                    const folderName = pathParts[0];
                    if (!folders[folderName]) {
                        folders[folderName] = [];
                    }
                    file.webkitRelativePath = file.webkitRelativePath;
                    folders[folderName].push(file);
                }
            });
            
            addFolders(folders);
            folderInput.value = '';
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
        
        function addFolders(folders) {
            const currentCount = Object.keys(selectedFolders).length;
            const newFolders = Object.keys(folders);
            
            if (currentCount + newFolders.length > 5) {
                showStatus('warning', '⚠️ Можно выбрать не более 5 папок. Сейчас выбрано ' + currentCount);
                return;
            }
            
            let added = 0;
            for (const [folderName, files] of Object.entries(folders)) {
                if (selectedFolders[folderName]) {
                    showStatus('warning', '⚠️ Папка "' + folderName + '" уже выбрана');
                    continue;
                }
                selectedFolders[folderName] = files;
                added++;
            }
            
            if (added > 0) {
                renderFolderList();
                showStatus('info', '✅ Добавлено ' + added + ' папок. Всего: ' + Object.keys(selectedFolders).length + '/5');
                addLog('📁 Добавлена папка: ' + Object.keys(folders).join(', '), 'info');
            }
        }
        
        function renderFolderList() {
            const folderNames = Object.keys(selectedFolders);
            
            if (folderNames.length === 0) {
                folderList.style.display = 'none';
                return;
            }
            
            folderList.style.display = 'block';
            folderListContent.innerHTML = '';
            
            folderNames.forEach((folderName, index) => {
                const files = selectedFolders[folderName];
                const fileCount = files.length;
                const adCount = countAds(files);
                
                const li = document.createElement('li');
                li.innerHTML = `
                    <span>
                        <strong>${index + 1}. ${folderName}</strong>
                        <span class="badge">${fileCount} файлов</span>
                        <span class="badge" style="background: #28a745;">${adCount} объявлений</span>
                    </span>
                    <button class="remove-btn" onclick="removeFolder('${folderName}')">×</button>
                `;
                folderListContent.appendChild(li);
            });
        }
        
        function countAds(files) {
            const folders = new Set();
            files.forEach(f => {
                const parts = f.webkitRelativePath.split('/');
                if (parts.length >= 2) {
                    const folder = parts[0] + '/' + parts[1];
                    folders.add(folder);
                }
            });
            return folders.size;
        }
        
        function removeFolder(folderName) {
            delete selectedFolders[folderName];
            renderFolderList();
            addLog('🗑️ Удалена папка: ' + folderName, 'warning');
            
            if (Object.keys(selectedFolders).length === 0) {
                folderList.style.display = 'none';
            }
        }
        
        function clearFolders() {
            selectedFolders = {};
            renderFolderList();
            folderList.style.display = 'none';
            addLog('🗑️ Все папки очищены', 'warning');
        }
        
        function addLog(message, type) {
            type = type || 'info';
            logDiv.style.display = 'block';
            const colors = {
                success: '#4caf50',
                error: '#f44336',
                warning: '#ff9800',
                info: '#2196f3'
            };
            const timestamp = new Date().toLocaleTimeString();
            logDiv.innerHTML += '<div style="color: ' + (colors[type] || '#d4d4d4') + '">[' + timestamp + '] ' + message + '</div>';
            logDiv.scrollTop = logDiv.scrollHeight;
        }
        
        function showStatus(type, message) {
            statusDiv.className = 'status ' + type;
            statusDiv.textContent = message;
            statusDiv.style.display = 'block';
        }
        
        function updateProgress(value, text) {
            progressBar.style.display = 'block';
            progress.style.width = value + '%';
            progress.textContent = text || Math.round(value) + '%';
        }
        
        function getReport() {
            window.open('/report/' + userId, '_blank');
        }
        
        function getDiagnostics() {
            window.open('/diagnostics', '_blank');
        }
        
        function stopPublish() {
            isStopped = true;
            stopBtn.style.display = 'none';
            uploadBtn.style.display = 'inline-block';
            addLog('⏹️ Остановка публикации...', 'warning');
            showStatus('warning', '⏹️ Публикация остановлена');
        }
        
        async function uploadFolders() {
            const folderNames = Object.keys(selectedFolders);
            
            if (folderNames.length === 0) {
                showStatus('error', '❌ Выберите хотя бы одну папку');
                return;
            }
            
            if (isProcessing) {
                addLog('⚠️ Обработка уже выполняется', 'warning');
                return;
            }
            
            const settings = {
                delay: parseInt(document.getElementById('delay').value) || 180,
                order: document.getElementById('order').value,
                maxPhotos: parseInt(document.getElementById('maxPhotos').value) || 3,
                onError: document.getElementById('onError').value
            };
            
            isProcessing = true;
            isStopped = false;
            uploadBtn.style.display = 'none';
            stopBtn.style.display = 'inline-block';
            
            showStatus('info', '⏳ Подготовка данных...');
            logDiv.innerHTML = '';
            addLog('🚀 Начинаем публикацию...', 'info');
            addLog('📁 Папок: ' + folderNames.length, 'info');
            addLog('⚙️ Настройки: задержка ' + settings.delay + 'с, порядок ' + settings.order, 'info');
            
            try {
                const allAds = [];
                let totalAds = 0;
                
                for (const folderName of folderNames) {
                    const files = selectedFolders[folderName];
                    const ads = await prepareFolderAds(folderName, files);
                    if (ads && ads.length > 0) {
                        allAds.push({
                            folderName: folderName,
                            ads: ads
                        });
                        totalAds += ads.length;
                        addLog('📤 Папка "' + folderName + '": ' + ads.length + ' объявлений', 'info');
                    } else {
                        addLog('⚠️ Папка "' + folderName + '": нет объявлений', 'warning');
                    }
                }
                
                if (allAds.length === 0) {
                    showStatus('error', '❌ Нет объявлений для публикации');
                    return;
                }
                
                addLog('📊 Всего объявлений: ' + totalAds, 'success');
                updateProgress(0, 'Начинаем...');
                
                const response = await fetch('/publish_multi', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        user_id: userId,
                        folders: allAds,
                        settings: settings
                    })
                });
                
                const result = await response.json();
                
                if (result.success) {
                    showStatus('success', '✅ Публикация завершена!');
                    addLog('✅ Успешно: ' + result.success_count, 'success');
                    addLog('❌ Ошибок: ' + result.error_count, 'error');
                    updateProgress(100, 'Завершено');
                    
                    if (result.success_count > 0) {
                        addLog('📊 Скачать отчет: /report/' + userId, 'info');
                    }
                } else {
                    showStatus('error', '❌ ' + result.message);
                    addLog('❌ Ошибка: ' + result.message, 'error');
                }
                
            } catch (error) {
                showStatus('error', '❌ Ошибка: ' + error.message);
                addLog('❌ Ошибка: ' + error.message, 'error');
            }
            
            isProcessing = false;
            uploadBtn.style.display = 'inline-block';
            stopBtn.style.display = 'none';
        }
        
        async function prepareFolderAds(folderName, files) {
            const ads = {};
            
            files.forEach(file => {
                const parts = file.webkitRelativePath.split('/');
                if (parts.length >= 2) {
                    const subFolder = parts[1];
                    if (!ads[subFolder]) {
                        ads[subFolder] = [];
                    }
                    ads[subFolder].push(file);
                }
            });
            
            const result = [];
            
            for (const [subFolder, subFiles] of Object.entries(ads)) {
                const txtFile = subFiles.find(f => f.name === 'info' || f.name.endsWith('.txt'));
                if (!txtFile) continue;
                
                try {
                    let fullText = await txtFile.text();
                    
                    let adText = fullText;
                    let metadataText = '';
                    
                    if (fullText.includes('#изъятая')) {
                        const parts = fullText.split('#изъятая');
                        adText = parts[0].trim();
                        metadataText = parts[1] ? parts[1].trim() : '';
                    }
                    
                    const imageFiles = subFiles
                        .filter(f => f.type && f.type.startsWith('image/'))
                        .slice(0, 10);
                    
                    const images = [];
                    for (const img of imageFiles) {
                        try {
                            const arrayBuffer = await img.arrayBuffer();
                            images.push({
                                name: img.name,
                                data: Array.from(new Uint8Array(arrayBuffer)),
                                type: img.type || 'image/jpeg'
                            });
                        } catch (e) {
                            addLog('⚠️ Ошибка чтения ' + img.name + ': ' + e.message, 'warning');
                        }
                    }
                    
                    result.push({
                        subFolder: subFolder,
                        adText: adText,
                        metadataText: metadataText,
                        images: images
                    });
                    
                } catch (e) {
                    addLog('⚠️ Ошибка обработки ' + subFolder + ': ' + e.message, 'warning');
                }
            }
            
            return result;
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
    """Страница загрузки с мульти-загрузкой"""
    return render_template_string(UPLOAD_PAGE_MULTI)

@app.route('/publish_multi', methods=['POST'])
def publish_multi():
    """Публикация из нескольких папок с настройками"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        folders = data.get('folders', [])
        settings = data.get('settings', {})
        
        if not user_id or not folders:
            return jsonify({'success': False, 'message': 'Нет данных'}), 400
        
        logger.info(f"📦 Мульти-публикация для пользователя {user_id}")
        logger.info(f"📁 Папок: {len(folders)}, Настройки: {settings}")
        
        result = publisher.publish_multi(user_id, folders, settings)
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"❌ Ошибка мульти-публикации: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/publish_folder', methods=['POST'])
def publish_folder():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        folder_data = data.get('folder')
        
        if not user_id or not folder_data:
            return jsonify({'success': False, 'message': 'Нет данных'}), 400
        
        folder_name = folder_data.get('folderName')
        ad_text = folder_data.get('adText')
        metadata_text = folder_data.get('metadataText')
        images = folder_data.get('images', [])
        
        logger.info(f"📦 Получена папка: {folder_name} от пользователя {user_id}")
        
        # Используем старый метод для обратной совместимости
        success, message = publisher.publish_single_folder(
            user_id, folder_name, ad_text, metadata_text, images
        )
        
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'message': message}), 500
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
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
                "3. Фото до 3 шт на объявление"
            )
            return jsonify({"ok": True}), 200
        
        if text and text.strip() == '/stop':
            publisher.stop(user_id)
            api.send_message(user_id, "⏹️ **Публикация остановлена!**\n\n✅ Все процессы остановлены\n🗑️ Временные файлы удалены")
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

@app.route('/diagnostics')
def diagnostics_page():
    """Страница диагностики"""
    report = diagnostics.get_diagnostics_report(include_logs=False)
    return jsonify(report)

@app.route('/diagnostics/download')
def diagnostics_download():
    """Скачать диагностический отчет"""
    report_path = diagnostics.save_report()
    if report_path:
        return send_file(report_path, as_attachment=True, 
                        download_name=os.path.basename(report_path))
    return "❌ Ошибка создания отчета", 500

@app.route('/diagnostics/logs')
def diagnostics_logs():
    """Получить логи"""
    logs = diagnostics.get_recent_logs(100)
    return f"<pre>{logs}</pre>"

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
