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
from werkzeug.exceptions import ClientDisconnected
from modules import Database, FileManager, Publisher, WebInterface
from modules.report_generator import ReportGenerator

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("MAX_TOKEN") or os.environ.get("MAX_BOT_TOKEN") or os.environ.get("TOKEN")
BASE_URL = "https://platform-api2.max.ru"
DATA_DIR = "/app/data"

if not TOKEN:
    logger.error("❌ ТОКЕН НЕ НАЙДЕН!")

db = Database()
fm = FileManager(DATA_DIR)

# Глобальные переменные для управления очередью
active_queues = {}
queue_lock = threading.Lock()

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
        """Отправляет сообщение с вложениями (фото) в чат"""
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

    def upload_file(self, file_data, filename='image.jpg'):
        """Загрузка файла на сервер MAX"""
        if not self.token:
            logger.error("❌ Нет токена для загрузки файла")
            return None
        try:
            if isinstance(file_data, bytes):
                files = {'file': (filename, file_data, 'image/jpeg')}
            else:
                logger.error(f"❌ Неподдерживаемый формат данных: {type(file_data)}")
                return None
            
            response = requests.post(
                f"{self.base_url}/files/upload",
                headers={"Authorization": self.token},
                files=files,
                timeout=60,
                verify=False
            )
            
            if response.status_code == 200:
                result = response.json()
                token = result.get('token') or result.get('data', {}).get('token') or result.get('id')
                if token:
                    logger.info(f"✅ Файл загружен: {token[:20] if token else 'None'}...")
                    return token
                else:
                    logger.error(f"❌ Не удалось получить токен: {result}")
                    return None
            else:
                logger.error(f"❌ Ошибка загрузки файла: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки файла: {e}")
            return None

api = APIClient()
publisher = Publisher(api, fm, db)
report_gen = ReportGenerator(fm, db)

# ========== HTML СТРАНИЦА С CHUNKED UPLOAD ==========
UPLOAD_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Загрузка объявлений</title>
    <style>
        * { box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; max-width: 900px; margin: 30px auto; padding: 20px; background: #f0f2f5; }
        .container { background: white; padding: 30px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1 { color: #1a1a2e; margin-top: 0; display: flex; align-items: center; gap: 10px; }
        .drop-zone { border: 2px dashed #4a6fa5; padding: 50px 20px; margin: 20px 0; border-radius: 12px; background: #f8faff; text-align: center; cursor: pointer; transition: all 0.3s; }
        .drop-zone:hover { background: #eef4ff; border-color: #2d4a7a; }
        .drop-zone.dragover { background: #d4edda; border-color: #28a745; }
        .drop-zone .icon { font-size: 56px; display: block; margin-bottom: 10px; }
        .drop-zone p { margin: 5px 0; color: #555; }
        input[type="file"] { display: none; }
        .btn { padding: 12px 28px; border: none; border-radius: 8px; cursor: pointer; font-size: 15px; font-weight: 600; transition: all 0.3s; }
        .btn-primary { background: #4a6fa5; color: white; }
        .btn-primary:hover { background: #2d4a7a; transform: translateY(-1px); }
        .btn-success { background: #28a745; color: white; }
        .btn-success:hover { background: #1e7e34; transform: translateY(-1px); }
        .btn-danger { background: #dc3545; color: white; }
        .btn-danger:hover { background: #b02a37; transform: translateY(-1px); }
        .btn-stop { background: #fd7e14; color: white; }
        .btn-stop:hover { background: #e06b0a; transform: translateY(-1px); }
        .btn-warning { background: #ffc107; color: #333; }
        .btn-warning:hover { background: #e0a800; transform: translateY(-1px); }
        .btn-outline { background: transparent; color: #4a6fa5; border: 2px solid #4a6fa5; }
        .btn-outline:hover { background: #4a6fa5; color: white; }
        .status { margin-top: 20px; padding: 15px 20px; border-radius: 8px; display: none; }
        .status.success { background: #d4edda; color: #155724; display: block; border-left: 4px solid #28a745; }
        .status.error { background: #f8d7da; color: #721c24; display: block; border-left: 4px solid #dc3545; }
        .status.info { background: #d1ecf1; color: #0c5460; display: block; border-left: 4px solid #17a2b8; }
        .status.warning { background: #fff3cd; color: #856404; display: block; border-left: 4px solid #ffc107; }
        .status.stop { background: #f8d7da; color: #721c24; display: block; border-left: 4px solid #dc3545; }
        .file-list { text-align: left; margin: 15px 0; padding: 0; list-style: none; max-height: 300px; overflow-y: auto; }
        .file-list li { background: #f8f9fa; padding: 10px 15px; margin: 4px 0; border-radius: 6px; border-left: 3px solid #4a6fa5; display: flex; justify-content: space-between; align-items: center; }
        .file-list li .count { background: #4a6fa5; color: white; padding: 2px 10px; border-radius: 20px; font-size: 12px; }
        .file-list li .status-badge { padding: 2px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; }
        .file-list li .status-badge.pending { background: #ffc107; color: #333; }
        .file-list li .status-badge.error { background: #dc3545; color: white; }
        .file-list li .status-badge.done { background: #28a745; color: white; }
        .file-list li .status-badge.stopped { background: #dc3545; color: white; }
        .progress-bar { width: 100%; height: 28px; background: #e9ecef; border-radius: 14px; overflow: hidden; margin: 15px 0; display: none; }
        .progress-bar .progress { height: 100%; background: linear-gradient(90deg, #28a745, #20c997); transition: width 0.4s; width: 0%; display: flex; align-items: center; justify-content: center; color: white; font-size: 13px; font-weight: 600; }
        .progress-bar .progress.stopped { background: linear-gradient(90deg, #dc3545, #c82333); }
        .instructions { background: #fff8e1; padding: 15px 20px; border-radius: 8px; margin: 15px 0; border-left: 4px solid #ffc107; font-size: 14px; line-height: 1.6; }
        .instructions code { background: #f8f9fa; padding: 2px 8px; border-radius: 4px; font-size: 13px; color: #d63384; }
        #log { background: #1e1e2e; color: #cdd6f4; padding: 15px; border-radius: 8px; font-family: 'Courier New', monospace; font-size: 12px; max-height: 350px; overflow-y: auto; margin: 15px 0; display: none; white-space: pre-wrap; line-height: 1.6; }
        .button-group { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 15px; }
        .selected-info { background: #e7f5ff; padding: 12px 18px; border-radius: 8px; margin: 10px 0; border-left: 3px solid #4a6fa5; }
        .footer { text-align: center; margin-top: 30px; color: #999; font-size: 13px; border-top: 1px solid #eee; padding-top: 20px; }
        .report-section { margin-top: 20px; padding: 20px; background: #f8f9fa; border-radius: 10px; border: 1px solid #dee2e6; text-align: center; }
        .report-section h3 { margin-top: 0; color: #1a1a2e; }
        .report-section .btn-group { display: flex; gap: 10px; justify-content: center; flex-wrap: wrap; }
        .queue-info { background: #e7f5ff; padding: 12px 18px; border-radius: 8px; margin: 10px 0; border-left: 3px solid #4a6fa5; display: none; font-weight: 500; }
        .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 15px 0; }
        .stats .stat { background: #f8f9fa; padding: 12px; border-radius: 8px; text-align: center; }
        .stats .stat .num { font-size: 24px; font-weight: 700; }
        .stats .stat .label { font-size: 12px; color: #666; }
        .stats .stat.success-stat .num { color: #28a745; }
        .stats .stat.error-stat .num { color: #dc3545; }
        .stats .stat.total-stat .num { color: #4a6fa5; }
        .chunk-info { font-size: 12px; color: #666; margin-top: 5px; }
        @media (max-width: 600px) {
            body { padding: 10px; margin: 10px; }
            .container { padding: 15px; }
            .stats { grid-template-columns: 1fr; }
            .button-group { flex-direction: column; }
            .btn { width: 100%; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>📤 Загрузка объявлений в MAX</h1>
        
        <div class="instructions">
            <strong>📌 Как подготовить папку:</strong><br>
            1️⃣ Создайте головную папку (любое название)<br>
            2️⃣ Внутри создайте подпапки объявлений: <code>1 -123456789</code>, <code>2 -987654321</code><br>
            3️⃣ В каждой подпапке: <code>info.txt</code> (текст) и фото (1-10 шт)<br>
            4️⃣ В тексте используйте разделитель <code>#изъятая</code>:<br>
            &nbsp;&nbsp;• Текст ДО разделителя — публикуется в чат<br>
            &nbsp;&nbsp;• Текст ПОСЛЕ разделителя — идет в отчет<br>
            5️⃣ Перетащите головную папку в поле ниже<br>
            6️⃣ Каждая папка отправляется отдельным запросом
        </div>
        
        <div class="drop-zone" id="dropZone">
            <span class="icon">📂</span>
            <p><strong>Перетащите головную папку сюда</strong></p>
            <p style="font-size: 14px; color: #888;">или</p>
            <button class="btn btn-primary" onclick="document.getElementById('folderInput').click()">Выбрать папку</button>
            <input type="file" id="folderInput" webkitdirectory multiple>
            <div class="chunk-info">📦 Загрузка по частям (макс. 50MB за раз)</div>
        </div>
        
        <div id="fileList" style="display:none;">
            <div class="selected-info" id="selectedInfo"></div>
            <ul class="file-list" id="fileListContent"></ul>
            <div class="button-group">
                <button class="btn btn-success" onclick="uploadFolder()">🚀 Загрузить</button>
                <button class="btn btn-stop" onclick="stopProcessing()">⏹ Остановить</button>
                <button class="btn btn-danger" onclick="clearFiles()">🗑️ Очистить</button>
            </div>
        </div>
        
        <div class="queue-info" id="queueInfo"></div>
        
        <div class="stats" id="stats" style="display:none;">
            <div class="stat total-stat">
                <div class="num" id="totalCount">0</div>
                <div class="label">Всего папок</div>
            </div>
            <div class="stat success-stat">
                <div class="num" id="successCount">0</div>
                <div class="label">✅ Успешно</div>
            </div>
            <div class="stat error-stat">
                <div class="num" id="errorCount">0</div>
                <div class="label">❌ Ошибок</div>
            </div>
        </div>
        
        <div class="progress-bar" id="progressBar">
            <div class="progress" id="progress">0%</div>
        </div>
        
        <div id="status" class="status"></div>
        <div id="log"></div>
        
        <div class="report-section">
            <h3>📊 Отчеты</h3>
            <p style="color: #666; font-size: 14px; margin-bottom: 15px;">
                После завершения публикации скачайте отчеты. Данные будут автоматически очищены.
            </p>
            <div class="btn-group">
                <button class="btn btn-success" onclick="getReport()">📥 Отчет (успешные)</button>
                <button class="btn btn-warning" onclick="getErrorReport()">⚠️ Отчет (ошибки)</button>
            </div>
            <div style="margin-top: 15px; display: flex; gap: 10px; justify-content: center; flex-wrap: wrap;">
                <button class="btn btn-outline" onclick="getStats()" style="font-size: 13px;">📊 Статистика</button>
            </div>
        </div>
        
        <div class="footer">⚡ MAX Bot | Загрузка объявлений v2.0</div>
    </div>

    <script>
        const urlParams = new URLSearchParams(window.location.search);
        const userId = urlParams.get('user_id') || 151296248;
        const CHUNK_SIZE = 2 * 1024 * 1024;
        
        let selectedFiles = [];
        let isProcessing = false;
        let isStopped = false;
        let processedCount = 0;
        let totalFolders = 0;
        let folderResults = [];
        let successCount = 0;
        let errorCount = 0;
        
        const dropZone = document.getElementById('dropZone');
        const folderInput = document.getElementById('folderInput');
        const fileList = document.getElementById('fileList');
        const fileListContent = document.getElementById('fileListContent');
        const selectedInfo = document.getElementById('selectedInfo');
        const statusDiv = document.getElementById('status');
        const logDiv = document.getElementById('log');
        const progressBar = document.getElementById('progressBar');
        const progress = document.getElementById('progress');
        const queueInfo = document.getElementById('queueInfo');
        const statsDiv = document.getElementById('stats');

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
                li.id = `folder-${folder.replace(/[^a-zA-Z0-9]/g, '_')}`;
                fileListContent.appendChild(li);
            });
            
            selectedInfo.textContent = `✅ Выбрано ${sortedFolders.length} папок, всего ${files.length} файлов`;
            fileList.style.display = 'block';
            showStatus('info', '📦 Нажмите "Загрузить" для отправки');
            statsDiv.style.display = 'none';
        }

        function clearFiles() {
            selectedFiles = [];
            fileList.style.display = 'none';
            statusDiv.style.display = 'none';
            progressBar.style.display = 'none';
            queueInfo.style.display = 'none';
            statsDiv.style.display = 'none';
            logDiv.style.display = 'none';
            progress.style.width = '0%';
            progress.textContent = '0%';
            progress.className = 'progress';
            folderInput.value = '';
            isStopped = false;
            processedCount = 0;
            totalFolders = 0;
            folderResults = [];
            successCount = 0;
            errorCount = 0;
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

        function getReport() {
            window.open(`/report/${userId}`, '_blank');
        }

        function getErrorReport() {
            window.open(`/report_errors/${userId}`, '_blank');
        }

        async function getStats() {
            try {
                const response = await fetch(`/stats/${userId}`);
                const data = await response.json();
                if (data.success) {
                    showStatus('info', `📊 Всего: ${data.total}, ✅ Успешно: ${data.success}, ❌ Ошибок: ${data.errors}`);
                } else {
                    showStatus('error', '❌ ' + data.message);
                }
            } catch (e) {
                showStatus('error', '❌ Ошибка получения статистики');
            }
        }

        function compressImage(file, maxWidth = 500, maxHeight = 500, quality = 0.5) {
            return new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.readAsDataURL(file);
                reader.onload = (event) => {
                    const img = new Image();
                    img.src = event.target.result;
                    img.onload = () => {
                        const canvas = document.createElement('canvas');
                        let width = img.width;
                        let height = img.height;
                        
                        if (width > height) {
                            if (width > maxWidth) {
                                height = height * (maxWidth / width);
                                width = maxWidth;
                            }
                        } else {
                            if (height > maxHeight) {
                                width = width * (maxHeight / height);
                                height = maxHeight;
                            }
                        }
                        
                        canvas.width = width;
                        canvas.height = height;
                        const ctx = canvas.getContext('2d');
                        ctx.drawImage(img, 0, 0, width, height);
                        
                        const mimeType = 'image/jpeg';
                        
                        canvas.toBlob((blob) => {
                            if (blob) {
                                const compressedFile = new File([blob], file.name.replace(/\\.[^.]+$/, '.jpg'), {
                                    type: mimeType,
                                    lastModified: Date.now()
                                });
                                resolve(compressedFile);
                            } else {
                                reject(new Error('Не удалось сжать изображение'));
                            }
                        }, mimeType, quality);
                    };
                    img.onerror = reject;
                };
                reader.onerror = reject;
            });
        }

        async function uploadFileInChunks(file, folderName, fileName) {
            const totalChunks = Math.ceil(file.size / CHUNK_SIZE);
            
            for (let i = 0; i < totalChunks; i++) {
                if (isStopped) {
                    throw new Error('Остановка пользователем');
                }
                
                const start = i * CHUNK_SIZE;
                const end = Math.min(start + CHUNK_SIZE, file.size);
                const chunk = file.slice(start, end);
                
                const formData = new FormData();
                formData.append('chunk', chunk);
                formData.append('chunk_index', i);
                formData.append('total_chunks', totalChunks);
                formData.append('user_id', userId);
                formData.append('folder_name', folderName);
                formData.append('file_name', fileName);
                
                const response = await fetch('/upload_chunk', {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                if (!result.success) {
                    throw new Error(result.message || 'Ошибка загрузки чанка');
                }
            }
            
            return true;
        }

        async function stopProcessing() {
            if (!isProcessing) {
                showStatus('warning', '⚠️ Нет активных процессов для остановки');
                return;
            }
            
            isStopped = true;
            showStatus('stop', '⏹ Остановка...');
            addLog('⏹ ПОЛУЧЕНА КОМАНДА ОСТАНОВКИ');
            
            try {
                const response = await fetch('/stop_processing', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ user_id: parseInt(userId) })
                });
                
                const result = await response.json();
                if (result.success) {
                    showStatus('stop', '⏹ Процесс остановлен!');
                    addLog(`✅ ${result.message}`);
                    progress.className = 'progress stopped';
                } else {
                    showStatus('error', `❌ Ошибка остановки: ${result.message}`);
                }
            } catch (error) {
                addLog(`❌ Ошибка при остановке: ${error.message}`);
            }
            
            isProcessing = false;
        }

        async function prepareFolderData(folderName, files) {
            const txtFile = files.find(f => f.name === 'info.txt' || f.name.endsWith('.txt'));
            if (!txtFile) {
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
            
            const imageFiles = files
                .filter(f => f.type && f.type.startsWith('image/'))
                .slice(0, 3);
            
            const images = [];
            for (const img of imageFiles) {
                try {
                    const compressed = await compressImage(img, 500, 500, 0.5);
                    
                    await uploadFileInChunks(compressed, folderName, compressed.name);
                    
                    const reader = new FileReader();
                    const dataUrl = await new Promise((resolve) => {
                        reader.onload = (e) => resolve(e.target.result);
                        reader.readAsDataURL(compressed);
                    });
                    
                    images.push({
                        name: compressed.name,
                        data: dataUrl,
                        type: compressed.type || 'image/jpeg',
                        originalSize: img.size,
                        compressedSize: compressed.size
                    });
                    
                    addLog(`✅ Фото ${img.name} сжато: ${(img.size/1024).toFixed(0)}KB -> ${(compressed.size/1024).toFixed(0)}KB (${Math.round((compressed.size/img.size)*100)}%)`);
                } catch (e) {
                    addLog(`⚠️ Ошибка обработки ${img.name}: ${e.message}`);
                    try {
                        const compressed = await compressImage(img, 400, 400, 0.4);
                        const reader = new FileReader();
                        const dataUrl = await new Promise((resolve) => {
                            reader.onload = (e) => resolve(e.target.result);
                            reader.readAsDataURL(compressed);
                        });
                        images.push({
                            name: compressed.name,
                            data: dataUrl,
                            type: compressed.type || 'image/jpeg'
                        });
                        addLog(`✅ Фото ${img.name} сжато (повторно): ${(compressed.size/1024).toFixed(0)}KB`);
                    } catch (e2) {
                        addLog(`⚠️ Не удалось обработать ${img.name}: ${e2.message}`);
                    }
                }
            }
            
            return {
                folderName: folderName,
                adText: adText,
                metadataText: metadataText,
                fullText: fullText,
                images: images
            };
        }

        async function uploadFolder() {
            if (selectedFiles.length === 0) {
                showStatus('error', '❌ Выберите папку для загрузки');
                return;
            }
            
            if (isProcessing) {
                addLog('⚠️ Обработка уже выполняется, подождите...');
                return;
            }
            
            isProcessing = true;
            isStopped = false;
            processedCount = 0;
            folderResults = [];
            successCount = 0;
            errorCount = 0;
            
            showStatus('info', '⏳ Подготовка данных...');
            progressBar.style.display = 'block';
            progress.style.width = '0%';
            progress.textContent = '0%';
            progress.className = 'progress';
            logDiv.textContent = '';
            statsDiv.style.display = 'grid';
            document.getElementById('totalCount').textContent = '0';
            document.getElementById('successCount').textContent = '0';
            document.getElementById('errorCount').textContent = '0';
            queueInfo.style.display = 'block';
            addLog('🚀 Начинаем обработку...');
            
            const folders = {};
            selectedFiles.forEach(file => {
                const pathParts = file.webkitRelativePath.split('/');
                if (pathParts.length >= 2) {
                    const folderName = pathParts[0] + '/' + pathParts[1];
                    if (!folders[folderName]) {
                        folders[folderName] = [];
                    }
                    folders[folderName].push(file);
                }
            });
            
            const folderNames = Object.keys(folders);
            totalFolders = folderNames.length;
            
            addLog(`📁 Найдено ${totalFolders} папок`);
            document.getElementById('totalCount').textContent = totalFolders;
            queueInfo.textContent = `📋 В очереди: ${totalFolders} папок | Обработано: 0/${totalFolders}`;
            showStatus('info', `⏳ Подготовка 0/${totalFolders} папок...`);
            
            for (let i = 0; i < folderNames.length; i++) {
                if (isStopped) {
                    addLog(`⏹ ОСТАНОВЛЕНО! Обработано ${i}/${totalFolders} папок`);
                    break;
                }
                
                const folderName = folderNames[i];
                const files = folders[folderName];
                
                const percent = Math.round((i / totalFolders) * 100);
                progress.style.width = percent + '%';
                progress.textContent = `${i}/${totalFolders}`;
                queueInfo.textContent = `📋 В очереди: ${totalFolders - i} папок | Обработано: ${i}/${totalFolders}`;
                showStatus('info', `⏳ Подготовка ${i+1}/${totalFolders}: ${folderName}`);
                
                try {
                    addLog(`📤 Подготовка ${i+1}/${totalFolders}: ${folderName}...`);
                    const folderData = await prepareFolderData(folderName, files);
                    
                    if (!folderData) {
                        addLog(`⚠️ Пропускаем ${folderName}: нет текстового файла`);
                        errorCount++;
                        folderResults.push(`❌ ${folderName}: нет текстового файла`);
                        document.getElementById('errorCount').textContent = errorCount;
                        continue;
                    }
                    
                    if (isStopped) {
                        addLog(`⏹ ОСТАНОВЛЕНО! Пропускаем ${folderName}`);
                        break;
                    }
                    
                    addLog(`📤 Отправка ${i+1}/${totalFolders}: ${folderName} (${folderData.images.length} фото)`);
                    
                    const response = await fetch('/publish_folder', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            user_id: parseInt(userId),
                            folder: folderData
                        })
                    });
                    
                    const result = await response.json();
                    
                    if (result.success) {
                        successCount++;
                        addLog(`✅ ${folderName}: опубликовано`);
                        folderResults.push(`✅ ${folderName}: успешно`);
                    } else {
                        errorCount++;
                        addLog(`❌ ${folderName}: ${result.message}`);
                        folderResults.push(`❌ ${folderName}: ${result.message}`);
                    }
                    
                    document.getElementById('successCount').textContent = successCount;
                    document.getElementById('errorCount').textContent = errorCount;
                    
                } catch (error) {
                    errorCount++;
                    addLog(`❌ ${folderName}: ошибка - ${error.message}`);
                    folderResults.push(`❌ ${folderName}: ${error.message}`);
                    document.getElementById('errorCount').textContent = errorCount;
                }
                
                processedCount = i + 1;
                await new Promise(r => setTimeout(r, 300));
            }
            
            if (isStopped) {
                progress.style.width = '100%';
                progress.textContent = `${processedCount}/${totalFolders} (Остановлено)`;
                progress.className = 'progress stopped';
                showStatus('stop', `⏹ Остановлено! Обработано ${processedCount}/${totalFolders} папок`);
                addLog(`⏹ ПРОЦЕСС ОСТАНОВЛЕН`);
                addLog(`📊 Обработано: ${successCount} успешно, ${errorCount} с ошибками`);
                isProcessing = false;
                return;
            }
            
            progress.style.width = '100%';
            progress.textContent = `${totalFolders}/${totalFolders}`;
            queueInfo.textContent = `✅ Завершено! Обработано ${totalFolders} папок`;
            
            if (errorCount === 0) {
                showStatus('success', `✅ Загружено ${successCount} папок!`);
                addLog(`✅ ВСЕ ${successCount} папок загружены!`);
            } else {
                showStatus('warning', `⚠️ Загружено ${successCount} папок, ${errorCount} с ошибками`);
                addLog(`⚠️ Загружено ${successCount} папок, ${errorCount} с ошибками`);
            }
            
            if (folderResults.length > 0) {
                addLog('\\n📋 Детали:');
                folderResults.slice(0, 20).forEach(r => addLog(r));
                if (folderResults.length > 20) {
                    addLog(`... и еще ${folderResults.length - 20} папок`);
                }
            }
            
            if (successCount > 0) {
                addLog(`\\n📊 Скачать отчет: /report/${userId}`);
                addLog(`⚠️ Скачать ошибки: /report_errors/${userId}`);
            }
            
            isProcessing = false;
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

# ===== ЗАГРУЗКА ПО ЧАСТЯМ =====
@app.route('/upload_chunk', methods=['POST'])
def upload_chunk():
    """Загрузка файла по частям"""
    try:
        chunk = request.files.get('chunk')
        chunk_index = request.form.get('chunk_index', 0)
        total_chunks = request.form.get('total_chunks', 1)
        user_id = request.form.get('user_id')
        folder_name = request.form.get('folder_name')
        file_name = request.form.get('file_name', 'image.jpg')
        
        if not chunk:
            return jsonify({'success': False, 'message': 'Нет данных'}), 400
        
        if not user_id:
            return jsonify({'success': False, 'message': 'Нет user_id'}), 400
        
        temp_dir = os.path.join(DATA_DIR, 'temp', str(user_id), folder_name)
        os.makedirs(temp_dir, exist_ok=True)
        
        chunk_filename = f"{file_name}.part_{chunk_index}"
        chunk_path = os.path.join(temp_dir, chunk_filename)
        chunk.save(chunk_path)
        
        if int(chunk_index) == int(total_chunks) - 1:
            final_path = os.path.join(temp_dir, file_name)
            with open(final_path, 'wb') as outfile:
                for i in range(int(total_chunks)):
                    part_file = os.path.join(temp_dir, f"{file_name}.part_{i}")
                    if os.path.exists(part_file):
                        with open(part_file, 'rb') as infile:
                            outfile.write(infile.read())
                        os.remove(part_file)
            
            file_size = os.path.getsize(final_path)
            logger.info(f"📦 Собран файл {file_name} размером {file_size} байт")
            
            return jsonify({
                'success': True,
                'message': 'Файл собран',
                'path': final_path,
                'size': file_size
            })
        
        return jsonify({'success': True, 'message': f'Чанк {chunk_index} загружен'})
        
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки чанка: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/publish_folder', methods=['POST'])
def publish_folder():
    try:
        data = request.get_json()
        
        if not data:
            logger.error("❌ Нет данных в запросе")
            return jsonify({'success': False, 'message': 'Нет данных'}), 400
        
        user_id = data.get('user_id')
        folder_data = data.get('folder')
        
        if not user_id or not folder_data:
            logger.error(f"❌ Нет user_id или folder_data: user_id={user_id}")
            return jsonify({'success': False, 'message': 'Нет данных'}), 400
        
        folder_name = folder_data.get('folderName')
        ad_text = folder_data.get('adText')
        metadata_text = folder_data.get('metadataText')
        images = folder_data.get('images', [])
        
        logger.info(f"📦 Получена папка: {folder_name} от пользователя {user_id}")
        logger.info(f"📝 Текст: {len(ad_text)} символов, 🖼️ Фото: {len(images)}")
        
        processed_images = []
        for img in images:
            try:
                if img.get('data') and img['data'].startswith('data:image'):
                    data_parts = img['data'].split(',')
                    if len(data_parts) > 1:
                        image_data = base64.b64decode(data_parts[1])
                        processed_images.append({
                            'name': img.get('name', 'image.jpg'),
                            'data': list(image_data),
                            'type': img.get('type', 'image/jpeg')
                        })
                    else:
                        processed_images.append(img)
                else:
                    processed_images.append(img)
            except Exception as e:
                logger.error(f"❌ Ошибка обработки изображения: {e}")
                processed_images.append(img)
        
        success, message = publisher.publish_single_folder(
            user_id, folder_name, ad_text, metadata_text, processed_images
        )
        
        try:
            temp_dir = os.path.join(DATA_DIR, 'temp', str(user_id), folder_name)
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
                logger.info(f"🗑️ Удалена временная папка: {temp_dir}")
        except Exception as e:
            logger.error(f"⚠️ Ошибка удаления временных файлов: {e}")
        
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'message': message}), 500
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/stop_processing', methods=['POST'])
def stop_processing():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        
        if not user_id:
            return jsonify({'success': False, 'message': 'Нет user_id'}), 400
        
        logger.info(f"⏹ ПОЛУЧЕНА КОМАНДА ОСТАНОВКИ для пользователя {user_id}")
        
        publisher.stop(user_id)
        
        try:
            temp_dir = os.path.join(DATA_DIR, 'temp', str(user_id))
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
                logger.info(f"🗑️ Удалена временная папка загрузки: {temp_dir}")
        except Exception as e:
            logger.error(f"⚠️ Ошибка удаления временных файлов: {e}")
        
        with queue_lock:
            if user_id in active_queues:
                queue_size = len(active_queues[user_id].get('queue', []))
                active_queues[user_id] = {
                    'queue': [],
                    'processing': False,
                    'stop_flag': True
                }
                logger.info(f"🗑️ Очищена очередь для {user_id} ({queue_size} элементов)")
            else:
                active_queues[user_id] = {
                    'queue': [],
                    'processing': False,
                    'stop_flag': True
                }
        
        api.send_message(
            user_id, 
            "⏹️ **Публикация остановлена!**\n\n"
            "✅ Все процессы остановлены\n"
            "🗑️ Временные файлы удалены\n"
            "🗑️ Очередь очищена"
        )
        
        return jsonify({
            'success': True, 
            'message': 'Процесс остановлен и очередь очищена',
            'cleaned': 'Временные файлы и очередь удалены'
        })
        
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
                "⚠️ **Отчет с ошибками:**\n"
                f"🔗 https://maxbot.bothost.tech/report_errors/{user_id}\n\n"
                "⏹ **Остановить публикацию:** `/stop`\n\n"
                "📋 **Инструкция:**\n"
                "1. Подготовьте папки с объявлениями\n"
                "2. Используйте разделитель #изъятая\n"
                "3. Фото до 3 шт на объявление"
            )
            return jsonify({"ok": True}), 200
        
        if text and text.strip() == '/stop':
            publisher.stop(user_id)
            
            try:
                temp_dir = os.path.join(DATA_DIR, 'temp', str(user_id))
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
            except:
                pass
            
            with queue_lock:
                if user_id in active_queues:
                    queue_size = len(active_queues[user_id].get('queue', []))
                    active_queues[user_id] = {
                        'queue': [],
                        'processing': False,
                        'stop_flag': True
                    }
                else:
                    active_queues[user_id] = {
                        'queue': [],
                        'processing': False,
                        'stop_flag': True
                    }
            
            api.send_message(
                user_id, 
                "⏹️ **Публикация остановлена!**\n\n"
                "✅ Все процессы остановлены\n"
                "🗑️ Временные файлы удалены\n"
                "🗑️ Очередь очищена"
            )
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
    <head>
        <title>Отчет</title>
        <style>
            body {{ font-family: Arial; max-width: 600px; margin: 50px auto; text-align: center; padding: 20px; }}
            h1 {{ color: #1a1a2e; }}
            .btn {{ display: inline-block; padding: 14px 35px; background: #28a745; color: white; text-decoration: none; border-radius: 8px; font-weight: 600; }}
            .btn:hover {{ background: #1e7e34; }}
            .links {{ margin-top: 30px; display: flex; gap: 15px; justify-content: center; flex-wrap: wrap; }}
            .links a {{ color: #4a6fa5; text-decoration: none; }}
            .links a:hover {{ text-decoration: underline; }}
        </style>
    </head>
    <body>
        <h1>📊 Отчет готов!</h1>
        <p style="color: #666;">Все данные будут автоматически очищены после скачивания</p>
        <br>
        <a href="{download_url}" class="btn">📥 Скачать отчет</a>
        <div class="links">
            <a href="/report_errors/{user_id}">⚠️ Отчет с ошибками</a>
            <a href="/upload">⬅️ Вернуться к загрузке</a>
        </div>
    </body>
    </html>
    """

@app.route('/report_errors/<int:user_id>')
def report_errors_page(user_id):
    report_path = report_gen.generate_error_report(user_id)
    if not report_path:
        return "❌ Нет ошибок для отчета", 404
    
    filename = os.path.basename(report_path)
    download_url = f"/download_report/{user_id}/{filename}"
    
    return f"""
    <html>
    <head>
        <title>Отчет об ошибках</title>
        <style>
            body {{ font-family: Arial; max-width: 600px; margin: 50px auto; text-align: center; padding: 20px; }}
            h1 {{ color: #1a1a2e; }}
            .btn {{ display: inline-block; padding: 14px 35px; background: #ffc107; color: #333; text-decoration: none; border-radius: 8px; font-weight: 600; }}
            .btn:hover {{ background: #e0a800; }}
            .links {{ margin-top: 30px; display: flex; gap: 15px; justify-content: center; flex-wrap: wrap; }}
            .links a {{ color: #4a6fa5; text-decoration: none; }}
            .links a:hover {{ text-decoration: underline; }}
        </style>
    </head>
    <body>
        <h1>⚠️ Отчет об ошибках</h1>
        <p style="color: #666;">Список папок, которые не удалось опубликовать</p>
        <br>
        <a href="{download_url}" class="btn">📥 Скачать отчет об ошибках</a>
        <div class="links">
            <a href="/report/{user_id}">📊 Основной отчет</a>
            <a href="/upload">⬅️ Вернуться к загрузке</a>
        </div>
    </body>
    </html>
    """

@app.route('/stats/<int:user_id>')
def stats_page(user_id):
    try:
        stats = db.get_stats(user_id)
        return jsonify({
            'success': True,
            'total': stats['total'],
            'success': stats['success'],
            'errors': stats['errors']
        })
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/download_report/<int:user_id>/<path:filename>')
def download_report(user_id, filename):
    try:
        user_folder = fm.get_user_folder(user_id)
        file_path = os.path.join(user_folder, filename)
        
        if not os.path.exists(file_path):
            return "❌ Файл не найден", 404
        
        return send_file(file_path, as_attachment=True, download_name=filename)
        
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

@app.errorhandler(Exception)
def handle_all_exceptions(error):
    logger.error(f"Критическая ошибка обработки запроса: {error}", exc_info=True)
    return jsonify({
        'success': False,
        'message': 'Внутренняя ошибка сервера',
        'details': str(error)
    }), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    if TOKEN:
        logger.info(f"✅ Токен найден (первые 10): {TOKEN[:10]}...")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
