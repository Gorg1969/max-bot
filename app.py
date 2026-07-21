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
from modules import Database, FileManager, Publisher, ReportGenerator

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

class APIClient:
    def __init__(self):
        self.token = TOKEN
        self.base_url = BASE_URL

    def upload_file(self, file_data, filename):
        """Загружает файл на сервер и возвращает токен"""
        if not self.token:
            return None
        try:
            files = {'file': (filename, file_data, 'image/jpeg')}
            response = requests.post(
                f"{self.base_url}/files",
                headers={"Authorization": self.token},
                files=files,
                timeout=30,
                verify=False
            )
            if response.status_code == 200:
                result = response.json()
                token = result.get('token')
                if token:
                    logger.info(f"✅ Файл загружен, токен: {token[:10]}...")
                    return token
                else:
                    logger.error(f"❌ Токен не получен: {result}")
                    return None
            else:
                logger.error(f"❌ Ошибка загрузки файла: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки файла: {e}")
            return None

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
        body { font-family: Arial; max-width: 900px; margin: 50px auto; padding: 20px; background: #f5f5f5; }
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
        .btn-warning { background: #ffc107; color: #333; }
        .btn-warning:hover { background: #e0a800; }
        .btn-secondary { background: #6c757d; color: white; }
        .btn-secondary:hover { background: #5a6268; }
        .btn-info { background: #17a2b8; color: white; }
        .btn-info:hover { background: #138496; }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .status { margin-top: 20px; padding: 15px; border-radius: 5px; display: none; }
        .status.success { background: #d4edda; color: #155724; display: block; border-left: 4px solid #28a745; }
        .status.error { background: #f8d7da; color: #721c24; display: block; border-left: 4px solid #dc3545; }
        .status.info { background: #d1ecf1; color: #0c5460; display: block; border-left: 4px solid #17a2b8; }
        .status.warning { background: #fff3cd; color: #856404; display: block; border-left: 4px solid #ffc107; }
        .status.paused { background: #e2e3e5; color: #383d41; display: block; border-left: 4px solid #6c757d; }
        .file-list { text-align: left; margin: 20px 0; padding: 0; list-style: none; }
        .file-list li { background: #f8f9fa; padding: 10px 15px; margin: 5px 0; border-radius: 5px; border-left: 3px solid #007bff; display: flex; justify-content: space-between; align-items: center; }
        .file-list li .count { background: #007bff; color: white; padding: 2px 10px; border-radius: 20px; font-size: 12px; }
        .file-list li.done { border-left-color: #28a745; background: #f0fff4; }
        .file-list li.done .count { background: #28a745; }
        .file-list li.error { border-left-color: #dc3545; background: #fff5f5; }
        .file-list li.error .count { background: #dc3545; }
        .file-list li.paused { border-left-color: #ffc107; background: #fffbf0; }
        .file-list li.paused .count { background: #ffc107; color: #333; }
        .file-list li .status-badge { font-size: 12px; padding: 2px 8px; border-radius: 12px; }
        .file-list li .status-badge.done { background: #28a745; color: white; }
        .file-list li .status-badge.error { background: #dc3545; color: white; }
        .file-list li .status-badge.pending { background: #ffc107; color: #333; }
        .file-list li .status-badge.paused { background: #6c757d; color: white; }
        .progress-bar { width: 100%; height: 25px; background: #e9ecef; border-radius: 10px; overflow: hidden; margin: 10px 0; display: none; }
        .progress-bar .progress { height: 100%; background: linear-gradient(90deg, #28a745, #20c997); transition: width 0.3s; width: 0%; display: flex; align-items: center; justify-content: center; color: white; font-size: 12px; font-weight: bold; }
        .progress-bar.paused .progress { background: linear-gradient(90deg, #6c757d, #adb5bd); }
        .instructions { background: #fff3cd; padding: 15px 20px; border-radius: 5px; margin: 20px 0; border-left: 4px solid #ffc107; }
        .instructions code { background: #f8f9fa; padding: 2px 8px; border-radius: 3px; font-size: 14px; color: #d63384; }
        #log { background: #1e1e1e; color: #d4d4d4; padding: 15px; border-radius: 5px; font-family: 'Courier New', monospace; font-size: 12px; max-height: 300px; overflow-y: auto; margin: 20px 0; display: none; white-space: pre-wrap; line-height: 1.5; }
        .button-group { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 15px; }
        .control-group { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 15px; padding: 15px; background: #f8f9fa; border-radius: 10px; border: 1px solid #dee2e6; }
        .selected-info { background: #e7f5ff; padding: 10px 15px; border-radius: 5px; margin: 10px 0; border-left: 3px solid #007bff; }
        .footer { text-align: center; margin-top: 30px; color: #999; font-size: 14px; }
        .report-section { margin-top: 20px; padding: 20px; background: #f8f9fa; border-radius: 10px; border: 1px solid #dee2e6; text-align: center; }
        .stats { display: flex; gap: 20px; justify-content: center; margin: 15px 0; flex-wrap: wrap; }
        .stats .stat-item { background: white; padding: 10px 20px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        .stats .stat-item .number { font-size: 24px; font-weight: bold; }
        .stats .stat-item .label { font-size: 12px; color: #666; }
        .stats .stat-item.success .number { color: #28a745; }
        .stats .stat-item.error .number { color: #dc3545; }
        .stats .stat-item.pending .number { color: #ffc107; }
        .stats .stat-item.total .number { color: #007bff; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📤 Загрузка объявлений</h1>
        
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
            <button class="btn btn-primary" onclick="document.getElementById('folderInput').click()">Выбрать папку</button>
            <input type="file" id="folderInput" webkitdirectory multiple>
        </div>
        
        <div id="fileList" style="display:none;">
            <div class="selected-info" id="selectedInfo"></div>
            <ul class="file-list" id="fileListContent"></ul>
            
            <div class="stats" id="stats" style="display:none;">
                <div class="stat-item total"><span class="number" id="statTotal">0</span><br><span class="label">Всего</span></div>
                <div class="stat-item success"><span class="number" id="statSuccess">0</span><br><span class="label">✅ Успешно</span></div>
                <div class="stat-item pending"><span class="number" id="statPending">0</span><br><span class="label">⏳ Ожидают</span></div>
                <div class="stat-item error"><span class="number" id="statError">0</span><br><span class="label">❌ Ошибки</span></div>
            </div>
            
            <div class="control-group">
                <button class="btn btn-success" id="btnStart" onclick="startPublish()">🚀 Старт</button>
                <button class="btn btn-warning" id="btnPause" onclick="togglePause()" disabled>⏸️ Пауза</button>
                <button class="btn btn-danger" id="btnStop" onclick="stopPublish()" disabled>⏹️ Стоп</button>
                <button class="btn btn-secondary" onclick="clearFiles()">🗑️ Очистить</button>
                <button class="btn btn-info" onclick="getReport()">📊 Отчет</button>
            </div>
        </div>
        
        <div class="progress-bar" id="progressBar">
            <div class="progress" id="progress">0%</div>
        </div>
        
        <div id="status" class="status"></div>
        <div id="log"></div>
        
        <div class="report-section">
            <button class="btn btn-primary" onclick="getReport()">📊 Скачать отчет</button>
            <p style="margin-top: 10px; color: #666; font-size: 14px;">Отчет создается в любое время на основе уже опубликованных папок</p>
        </div>
        
        <div class="footer">⚡ MAX Bot | Загрузка объявлений</div>
    </div>

    <script>
        const urlParams = new URLSearchParams(window.location.search);
        const userId = urlParams.get('user_id') || 151296248;
        
        let selectedFiles = [];
        let isPublishing = false;
        let isPaused = false;
        let isStopped = false;
        let currentIndex = 0;
        let folderResults = [];
        let totalFolders = 0;
        let pollInterval = null;
        
        const dropZone = document.getElementById('dropZone');
        const folderInput = document.getElementById('folderInput');
        const fileList = document.getElementById('fileList');
        const fileListContent = document.getElementById('fileListContent');
        const selectedInfo = document.getElementById('selectedInfo');
        const statusDiv = document.getElementById('status');
        const logDiv = document.getElementById('log');
        const progressBar = document.getElementById('progressBar');
        const progress = document.getElementById('progress');
        const statsDiv = document.getElementById('stats');
        
        const btnStart = document.getElementById('btnStart');
        const btnPause = document.getElementById('btnPause');
        const btnStop = document.getElementById('btnStop');

        dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('dragover'); });
        dropZone.addEventListener('dragleave', () => { dropZone.classList.remove('dragover'); });
        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            if (isPublishing) {
                showStatus('warning', '⚠️ Сначала остановите или завершите публикацию');
                return;
            }
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
            if (isPublishing) {
                showStatus('warning', '⚠️ Сначала остановите или завершите публикацию');
                return;
            }
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
            const folders = new Map();
            
            files.forEach(f => {
                const parts = f.webkitRelativePath.split('/');
                if (parts.length >= 2) {
                    const folder = parts[0] + '/' + parts[1];
                    if (!folders.has(folder)) {
                        folders.set(folder, { files: [], count: 0 });
                    }
                    folders.get(folder).files.push(f);
                    folders.get(folder).count++;
                }
            });
            
            const sortedFolders = Array.from(folders.keys()).sort();
            totalFolders = sortedFolders.length;
            folderResults = sortedFolders.map(name => ({ name, status: 'pending' }));
            
            sortedFolders.forEach((folder, index) => {
                const data = folders.get(folder);
                const li = document.createElement('li');
                li.id = 'folder-' + index;
                const displayName = folder.includes('/') ? folder.split('/')[1] : folder;
                li.innerHTML = `
                    <span>📁 <strong>${displayName}</strong></span>
                    <span>
                        <span class="count">${data.count} файлов</span>
                        <span class="status-badge pending" id="badge-${index}">⏳ ожидает</span>
                    </span>
                `;
                fileListContent.appendChild(li);
            });
            
            selectedInfo.textContent = `✅ Выбрано ${sortedFolders.length} папок, всего ${files.length} файлов`;
            fileList.style.display = 'block';
            statsDiv.style.display = 'flex';
            updateStats();
            showStatus('info', '📦 Нажмите "Старт" для начала публикации');
            
            btnStart.disabled = false;
            btnPause.disabled = true;
            btnStop.disabled = true;
        }

        function updateStats() {
            const total = folderResults.length;
            const success = folderResults.filter(r => r.status === 'success').length;
            const errors = folderResults.filter(r => r.status === 'error').length;
            const pending = folderResults.filter(r => r.status === 'pending' || r.status === 'processing').length;
            
            document.getElementById('statTotal').textContent = total;
            document.getElementById('statSuccess').textContent = success;
            document.getElementById('statError').textContent = errors;
            document.getElementById('statPending').textContent = pending;
        }

        function updateFolderStatus(index, status, message) {
            const badge = document.getElementById('badge-' + index);
            const li = document.getElementById('folder-' + index);
            if (!badge || !li) return;
            
            li.className = '';
            if (status === 'success') {
                li.classList.add('done');
                badge.className = 'status-badge done';
                badge.textContent = '✅ готово';
            } else if (status === 'error') {
                li.classList.add('error');
                badge.className = 'status-badge error';
                badge.textContent = '❌ ' + (message || 'ошибка');
            } else if (status === 'processing') {
                badge.className = 'status-badge pending';
                badge.textContent = '⏳ публикуется...';
            } else if (status === 'paused') {
                li.classList.add('paused');
                badge.className = 'status-badge paused';
                badge.textContent = '⏸️ на паузе';
            } else {
                badge.className = 'status-badge pending';
                badge.textContent = '⏳ ожидает';
            }
            
            if (status !== 'paused') {
                folderResults[index].status = status;
            }
            updateStats();
        }

        function clearFiles() {
            if (isPublishing) {
                showStatus('warning', '⚠️ Сначала остановите публикацию');
                return;
            }
            selectedFiles = [];
            fileList.style.display = 'none';
            statsDiv.style.display = 'none';
            statusDiv.style.display = 'none';
            progressBar.style.display = 'none';
            progressBar.className = 'progress-bar';
            logDiv.style.display = 'none';
            progress.style.width = '0%';
            progress.textContent = '0%';
            folderInput.value = '';
            folderResults = [];
            currentIndex = 0;
            isPaused = false;
            isStopped = false;
            btnStart.disabled = true;
            btnPause.disabled = true;
            btnStop.disabled = true;
            btnPause.textContent = '⏸️ Пауза';
            if (pollInterval) {
                clearInterval(pollInterval);
                pollInterval = null;
            }
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

        async function prepareFolderData(folderName, files) {
            const txtFile = files.find(f => f.name === 'info' || f.name.endsWith('.txt'));
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
                    addLog(`⚠️ Ошибка чтения ${img.name}: ${e.message}`);
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

        function getFolders() {
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
            return folders;
        }

        async function startPublish() {
            if (selectedFiles.length === 0) {
                showStatus('error', '❌ Выберите папку для загрузки');
                return;
            }
            
            if (isPublishing) {
                addLog('⚠️ Публикация уже выполняется');
                return;
            }
            
            // Если была пауза, возобновляем
            if (isPaused) {
                resumePublish();
                return;
            }
            
            // Новая публикация
            isPublishing = true;
            isPaused = false;
            isStopped = false;
            currentIndex = 0;
            
            // Сбрасываем статусы
            folderResults.forEach((r, i) => {
                r.status = 'pending';
                updateFolderStatus(i, 'pending');
            });
            
            btnStart.disabled = true;
            btnPause.disabled = false;
            btnStop.disabled = false;
            btnStart.textContent = '⏳ Идет...';
            
            showStatus('info', '⏳ Начинаем публикацию...');
            progressBar.style.display = 'block';
            progressBar.className = 'progress-bar';
            progress.style.width = '0%';
            progress.textContent = '0%';
            logDiv.textContent = '';
            addLog('🚀 Начинаем публикацию...');
            
            const folders = getFolders();
            const folderNames = Object.keys(folders);
            totalFolders = folderNames.length;
            
            addLog(`📁 Найдено ${totalFolders} папок`);
            
            // Запускаем процесс
            await publishNext(folders, folderNames);
        }

        async function publishNext(folders, folderNames) {
            while (currentIndex < folderNames.length) {
                // Проверяем стоп
                if (isStopped) {
                    addLog('⏹️ Публикация остановлена пользователем');
                    showStatus('warning', '⏹️ Публикация остановлена');
                    finishPublish();
                    return;
                }
                
                // Проверяем паузу
                if (isPaused) {
                    addLog('⏸️ Публикация на паузе');
                    showStatus('paused', '⏸️ Публикация на паузе. Нажмите "Старт" для продолжения');
                    progressBar.className = 'progress-bar paused';
                    btnStart.disabled = false;
                    btnStart.textContent = '▶️ Продолжить';
                    btnPause.disabled = true;
                    return;
                }
                
                const folderName = folderNames[currentIndex];
                const files = folders[folderName];
                
                const percent = Math.round((currentIndex / totalFolders) * 100);
                progress.style.width = percent + '%';
                progress.textContent = `${currentIndex}/${totalFolders}`;
                showStatus('info', `⏳ Публикация ${currentIndex+1}/${totalFolders}: ${folderName}`);
                
                updateFolderStatus(currentIndex, 'processing');
                addLog(`📤 ${currentIndex+1}/${totalFolders}: ${folderName}...`);
                
                try {
                    const folderData = await prepareFolderData(folderName, files);
                    
                    if (!folderData) {
                        addLog(`⚠️ Пропускаем ${folderName}: нет текстового файла`);
                        folderResults[currentIndex].status = 'error';
                        updateFolderStatus(currentIndex, 'error', 'нет текста');
                        currentIndex++;
                        continue;
                    }
                    
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
                        addLog(`✅ ${folderName}: опубликовано`);
                        folderResults[currentIndex].status = 'success';
                        updateFolderStatus(currentIndex, 'success');
                    } else {
                        addLog(`❌ ${folderName}: ${result.message}`);
                        folderResults[currentIndex].status = 'error';
                        updateFolderStatus(currentIndex, 'error', result.message);
                    }
                    
                } catch (error) {
                    addLog(`❌ ${folderName}: ошибка - ${error.message}`);
                    folderResults[currentIndex].status = 'error';
                    updateFolderStatus(currentIndex, 'error', error.message);
                }
                
                currentIndex++;
                updateStats();
                await new Promise(r => setTimeout(r, 300));
            }
            
            // Все папки обработаны
            finishPublish();
        }

        function togglePause() {
            if (isPublishing && !isPaused) {
                isPaused = true;
                btnPause.textContent = '⏸️ Пауза...';
                btnPause.disabled = true;
                addLog('⏸️ Пауза запрошена...');
            }
        }

        function resumePublish() {
            if (!isPaused) return;
            
            isPaused = false;
            btnStart.disabled = true;
            btnStart.textContent = '⏳ Идет...';
            btnPause.disabled = false;
            btnPause.textContent = '⏸️ Пауза';
            progressBar.className = 'progress-bar';
            
            addLog('▶️ Возобновляем публикацию...');
            showStatus('info', '▶️ Публикация возобновлена');
            
            const folders = getFolders();
            const folderNames = Object.keys(folders);
            publishNext(folders, folderNames);
        }

        function stopPublish() {
            if (!isPublishing) return;
            
            if (confirm('⏹️ Остановить публикацию? Все опубликованные папки останутся в отчете.')) {
                isStopped = true;
                isPaused = false;
                btnStop.disabled = true;
                addLog('⏹️ Остановка публикации...');
                showStatus('warning', '⏹️ Публикация останавливается...');
            }
        }

        function finishPublish() {
            isPublishing = false;
            isPaused = false;
            isStopped = false;
            
            progress.style.width = '100%';
            progress.textContent = `${totalFolders}/${totalFolders}`;
            
            const success = folderResults.filter(r => r.status === 'success').length;
            const errors = folderResults.filter(r => r.status === 'error').length;
            const total = folderResults.length;
            
            if (errors === 0 && total > 0) {
                showStatus('success', `✅ Все ${total} папок опубликованы!`);
                addLog(`✅ ВСЕ ${total} папок опубликованы!`);
            } else if (total > 0) {
                showStatus('warning', `⚠️ Опубликовано ${success} папок, ${errors} с ошибками`);
                addLog(`⚠️ Опубликовано ${success} папок, ${errors} с ошибками`);
            }
            
            btnStart.disabled = false;
            btnStart.textContent = '🚀 Старт';
            btnPause.disabled = true;
            btnPause.textContent = '⏸️ Пауза';
            btnStop.disabled = true;
            
            if (success > 0) {
                addLog(`\\n📊 Скачать отчет: /report/${userId}`);
                showStatus('success', `✅ Опубликовано ${success} папок! Нажмите "Отчет" для скачивания`);
            }
            
            updateStats();
        }

        // Проверка статуса публикации (для восстановления после перезагрузки)
        async function checkPublishStatus() {
            try {
                const response = await fetch(`/publish_status/${userId}`);
                const data = await response.json();
                if (data.is_running) {
                    showStatus('info', '⏳ Публикация уже выполняется...');
                }
            } catch (e) {
                // Игнорируем
            }
        }
        
        // Запускаем проверку при загрузке
        // checkPublishStatus();
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
        logger.info(f"📝 Текст: {len(ad_text)} символов, 🖼️ Фото: {len(images)}")
        
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

@app.route('/publish_status/<int:user_id>')
def publish_status(user_id):
    return jsonify({
        'is_running': publisher.is_running(user_id),
        'is_paused': publisher.is_paused(user_id)
    })

@app.route('/pause_publish/<int:user_id>', methods=['POST'])
def pause_publish(user_id):
    publisher.pause(user_id)
    return jsonify({'success': True, 'message': 'Публикация на паузе'})

@app.route('/resume_publish/<int:user_id>', methods=['POST'])
def resume_publish(user_id):
    publisher.resume(user_id)
    return jsonify({'success': True, 'message': 'Публикация возобновлена'})

@app.route('/stop_publish/<int:user_id>', methods=['POST'])
def stop_publish(user_id):
    publisher.stop(user_id)
    return jsonify({'success': True, 'message': 'Публикация остановлена'})

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
                "⏹ **Остановить публикацию:** `/stop`\n"
                "⏸ **Пауза:** `/pause`\n"
                "▶️ **Продолжить:** `/resume`\n\n"
                "📋 **Инструкция:**\n"
                "1. Подготовьте папки с объявлениями\n"
                "2. Используйте разделитель #изъятая\n"
                "3. Фото до 10 шт на объявление"
            )
            return jsonify({"ok": True}), 200
        
        if text and text.strip() == '/stop':
            publisher.stop(user_id)
            api.send_message(user_id, "⏹️ **Публикация остановлена!**\n\n✅ Все процессы остановлены\n📊 Отчет доступен по команде /report")
            return jsonify({"ok": True}), 200
        
        if text and text.strip() == '/pause':
            publisher.pause(user_id)
            api.send_message(user_id, "⏸️ **Публикация на паузе!**\n\n▶️ Для продолжения используйте /resume")
            return jsonify({"ok": True}), 200
        
        if text and text.strip() == '/resume':
            publisher.resume(user_id)
            api.send_message(user_id, "▶️ **Публикация возобновлена!**")
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
