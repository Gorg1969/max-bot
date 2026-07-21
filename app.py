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
        
        try:
            response = requests.post(
                f"{self.base_url}/uploads",
                headers={"Authorization": self.token},
                params={"type": "image"},
                timeout=30,
                verify=False
            )
            
            if response.status_code != 200:
                logger.error(f"❌ Ошибка получения URL: {response.status_code} - {response.text[:200]}")
                return None
            
            try:
                upload_data = response.json()
            except ValueError:
                raw_text = response.text.strip()
                logger.error(f"❌ Невалидный JSON: {raw_text[:200]}")
                return None
            
            upload_url = upload_data.get('url')
            if not upload_url:
                logger.error(f"❌ Не получен URL: {upload_data}")
                return None
            
            files = {'data': (filename, image_bytes, 'image/jpeg')}
            
            upload_response = requests.post(
                upload_url,
                files=files,
                timeout=60,
                verify=False
            )
            
            if upload_response.status_code != 200:
                logger.error(f"❌ Ошибка загрузки: {upload_response.status_code} - {upload_response.text[:200]}")
                return None
            
            try:
                upload_result = upload_response.json()
            except ValueError:
                raw_text = upload_response.text.strip()
                logger.error(f"❌ Невалидный JSON в ответе: {raw_text[:200]}")
                return None
            
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
                return None
            
            logger.info(f"✅ Файл загружен, токен: {token[:20]}...")
            return token
            
        except requests.exceptions.Timeout:
            logger.error("❌ Таймаут при загрузке файла")
            return None
        except requests.exceptions.ConnectionError:
            logger.error("❌ Ошибка соединения при загрузке файла")
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки: {e}")
            import traceback
            traceback.print_exc()
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
    <title>Загрузка объявлений</title>
    <style>
        body { font-family: Arial; max-width: 900px; margin: 50px auto; padding: 20px; background: #f5f5f5; }
        .container { background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1 { color: #333; margin-top: 0; display: flex; align-items: center; gap: 10px; }
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
        .btn-stop { background: #fd7e14; color: white; }
        .btn-stop:hover { background: #e06b0a; }
        .btn-info { background: #17a2b8; color: white; }
        .btn-info:hover { background: #138496; }
        .btn-warning { background: #ffc107; color: #333; }
        .btn-warning:hover { background: #e0a800; }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .status { margin-top: 20px; padding: 15px; border-radius: 5px; display: none; }
        .status.success { background: #d4edda; color: #155724; display: block; border-left: 4px solid #28a745; }
        .status.error { background: #f8d7da; color: #721c24; display: block; border-left: 4px solid #dc3545; }
        .status.info { background: #d1ecf1; color: #0c5460; display: block; border-left: 4px solid #17a2b8; }
        .status.warning { background: #fff3cd; color: #856404; display: block; border-left: 4px solid #ffc107; }
        .status.stop { background: #f8d7da; color: #721c24; display: block; border-left: 4px solid #dc3545; }
        .file-list { text-align: left; margin: 20px 0; padding: 0; list-style: none; max-height: 300px; overflow-y: auto; }
        .file-list li { background: #f8f9fa; padding: 10px 15px; margin: 5px 0; border-radius: 5px; border-left: 3px solid #007bff; display: flex; justify-content: space-between; align-items: center; }
        .file-list li .count { background: #007bff; color: white; padding: 2px 10px; border-radius: 20px; font-size: 12px; }
        .progress-bar { width: 100%; height: 25px; background: #e9ecef; border-radius: 10px; overflow: hidden; margin: 10px 0; display: none; }
        .progress-bar .progress { height: 100%; background: linear-gradient(90deg, #28a745, #20c997); transition: width 0.3s; width: 0%; display: flex; align-items: center; justify-content: center; color: white; font-size: 12px; font-weight: bold; }
        .progress-bar .progress.stopped { background: linear-gradient(90deg, #dc3545, #c82333); }
        .instructions { background: #fff3cd; padding: 15px 20px; border-radius: 5px; margin: 20px 0; border-left: 4px solid #ffc107; font-size: 14px; line-height: 1.6; }
        .instructions code { background: #f8f9fa; padding: 2px 8px; border-radius: 3px; font-size: 13px; color: #d63384; }
        #log { background: #1e1e1e; color: #d4d4d4; padding: 15px; border-radius: 5px; font-family: 'Courier New', monospace; font-size: 12px; max-height: 350px; overflow-y: auto; margin: 20px 0; display: none; white-space: pre-wrap; line-height: 1.5; }
        .button-group { display: flex; gap: 10px; flex-wrap: wrap; margin-top: 15px; }
        .selected-info { background: #e7f5ff; padding: 10px 15px; border-radius: 5px; margin: 10px 0; border-left: 3px solid #007bff; }
        .footer { text-align: center; margin-top: 30px; color: #999; font-size: 14px; border-top: 1px solid #eee; padding-top: 20px; }
        .report-section { margin-top: 20px; padding: 20px; background: #f8f9fa; border-radius: 10px; border: 1px solid #dee2e6; text-align: center; }
        .report-section .btn-group { display: flex; gap: 10px; align-items: center; justify-content: center; flex-wrap: wrap; }
        #reportStatus { margin-top: 15px; padding: 15px; border-radius: 5px; display: none; font-weight: 500; white-space: pre-line; }
        .queue-info { background: #e7f5ff; padding: 10px 15px; border-radius: 5px; margin: 10px 0; border-left: 3px solid #007bff; display: none; font-weight: 500; }
        .photo-progress { margin: 5px 0; font-size: 13px; color: #666; }
        .clear-btn { background: #dc3545; color: white; }
        .clear-btn:hover { background: #c82333; }
        @media (max-width: 600px) {
            body { padding: 10px; margin: 10px; }
            .container { padding: 15px; }
            .button-group { flex-direction: column; }
            .btn { width: 100%; }
            .report-section .btn-group { flex-direction: column; }
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
            6️⃣ Каждая папка отправляется отдельным запросом<br>
            7️⃣ <strong>Максимум 10 фото</strong>
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
            <div class="button-group">
                <button class="btn btn-success" onclick="uploadFolder()">🚀 Загрузить</button>
                <button class="btn btn-stop" onclick="stopProcessing()">⏹ Остановить</button>
                <button class="btn btn-danger" onclick="clearFiles()">🗑️ Очистить список</button>
                <button class="btn btn-danger clear-btn" onclick="clearAllData()">🗑️ Очистить БД</button>
            </div>
        </div>
        
        <div class="queue-info" id="queueInfo"></div>
        
        <div class="progress-bar" id="progressBar">
            <div class="progress" id="progress">0%</div>
        </div>
        
        <div id="status" class="status"></div>
        <div id="log"></div>
        
        <div class="report-section">
            <div class="btn-group">
                <button class="btn btn-primary" id="reportBtn" onclick="getReport()" disabled>
                    📊 Скачать отчет
                </button>
                <button class="btn btn-info" onclick="checkReportStatus()">
                    🔄 Проверить статус
                </button>
                <button class="btn btn-warning" onclick="forceUpdateLinks()">
                    🔄 Обновить ссылки
                </button>
                <button class="btn btn-danger clear-btn" onclick="clearAllData()">
                    🗑️ Очистить все
                </button>
            </div>
            <div id="reportStatus"></div>
            <p style="margin-top: 10px; color: #666; font-size: 14px;">
                После публикации подождите 1-2 минуты, затем нажмите "Проверить статус"
            </p>
        </div>
        
        <div class="footer">⚡ MAX Bot | Загрузка объявлений v2.0</div>
    </div>

    <script>
        const urlParams = new URLSearchParams(window.location.search);
        const userId = urlParams.get('user_id') || 151296248;
        
        let selectedFiles = [];
        let isProcessing = false;
        let isStopped = false;
        let processedCount = 0;
        let totalFolders = 0;
        let successCount = 0;
        let errorCount = 0;
        let reportReady = false;
        let statusCheckInterval = null;
        
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
        const reportBtn = document.getElementById('reportBtn');
        const reportStatus = document.getElementById('reportStatus');

        // 🔥 ПЕРЕХВАТЫВАЕМ ВСЕ ОШИБКИ FETCH ДЛЯ ДИАГНОСТИКИ
        const originalFetch = window.fetch;
        window.fetch = function(...args) {
            return originalFetch.apply(this, args).then(async (response) => {
                const clone = response.clone();
                const text = await clone.text();
                
                const contentType = response.headers.get('content-type');
                if (contentType && contentType.includes('application/json')) {
                    try {
                        JSON.parse(text);
                    } catch (e) {
                        console.error('❌ НЕВАЛИДНЫЙ JSON в ответе:', text);
                        console.error('❌ URL:', response.url);
                        console.error('❌ Статус:', response.status);
                    }
                }
                
                return response;
            });
        };

        document.addEventListener('DOMContentLoaded', function() {
            setTimeout(checkReportStatus, 3000);
        });

        window.addEventListener('beforeunload', function() {
            if (statusCheckInterval) {
                clearInterval(statusCheckInterval);
            }
        });

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
        }

        function clearFiles() {
            selectedFiles = [];
            fileList.style.display = 'none';
            statusDiv.style.display = 'none';
            progressBar.style.display = 'none';
            queueInfo.style.display = 'none';
            logDiv.style.display = 'none';
            progress.style.width = '0%';
            progress.textContent = '0%';
            progress.className = 'progress';
            folderInput.value = '';
            isStopped = false;
            processedCount = 0;
            totalFolders = 0;
            successCount = 0;
            errorCount = 0;
            reportReady = false;
            reportBtn.disabled = true;
            reportStatus.style.display = 'none';
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
            if (!reportReady) {
                showStatus('warning', '⏳ Отчет еще не готов, подождите...');
                return;
            }
            window.open(`/report/${userId}`, '_blank');
        }

        // 🔥 ОБНОВЛЕННАЯ ФУНКЦИЯ С ОБРАБОТКОЙ ОШИБОК JSON
        async function checkReportStatus() {
            try {
                const response = await fetch(`/report_status/${userId}`);
                const text = await response.text();
                
                // Удаляем лишний текст до первой {
                let cleanText = text;
                const firstBrace = text.indexOf('{');
                if (firstBrace > 0) {
                    cleanText = text.substring(firstBrace);
                    console.log('🧹 Удален лишний текст:', text.substring(0, firstBrace));
                }
                
                let result;
                try {
                    result = JSON.parse(cleanText);
                } catch (parseError) {
                    console.error('❌ Ошибка парсинга JSON:', parseError);
                    console.log('📄 Полученный текст:', text);
                    console.log('📄 Очищенный текст:', cleanText);
                    
                    reportStatus.style.display = 'block';
                    reportStatus.className = 'status error';
                    reportStatus.textContent = '❌ Ошибка сервера: ' + text.substring(0, 200);
                    reportBtn.disabled = true;
                    reportReady = false;
                    return;
                }
                
                if (result.error) {
                    reportStatus.style.display = 'block';
                    reportStatus.className = 'status error';
                    reportStatus.textContent = '❌ ' + result.error;
                    reportBtn.disabled = true;
                    reportReady = false;
                    return;
                }
                
                reportStatus.style.display = 'block';
                let statusText = `📊 Всего: ${result.total} | ✅ Готово: ${result.success}`;
                
                if (result.pending > 0) {
                    statusText += ` | ⏳ Ожидают: ${result.pending}`;
                    reportStatus.className = 'status info';
                    statusText += '\\n⏳ Подождите, ссылки еще формируются...';
                    reportBtn.disabled = true;
                    reportReady = false;
                } else if (result.failed > 0) {
                    statusText += ` | ❌ Ошибок: ${result.failed}`;
                    reportStatus.className = 'status warning';
                    if (result.success > 0) {
                        statusText += '\\n⚠️ Часть публикаций завершилась с ошибкой';
                        reportBtn.disabled = false;
                        reportReady = true;
                    } else {
                        statusText += '\\n❌ Все публикации завершились с ошибкой';
                        reportBtn.disabled = true;
                        reportReady = false;
                    }
                } else if (result.ready && result.success > 0) {
                    reportStatus.className = 'status success';
                    statusText += '\\n✅ Отчет готов! Нажмите "Скачать отчет"';
                    reportBtn.disabled = false;
                    reportReady = true;
                } else {
                    reportStatus.className = 'status info';
                    statusText += '\\n⏳ Нет готовых публикаций';
                    reportBtn.disabled = true;
                    reportReady = false;
                }
                
                reportStatus.textContent = statusText;
                
                if (result.pending > 0) {
                    if (statusCheckInterval) {
                        clearInterval(statusCheckInterval);
                    }
                    statusCheckInterval = setInterval(checkReportStatus, 10000);
                } else {
                    if (statusCheckInterval) {
                        clearInterval(statusCheckInterval);
                        statusCheckInterval = null;
                    }
                }
                
            } catch (error) {
                console.error('❌ Ошибка проверки статуса:', error);
                reportStatus.style.display = 'block';
                reportStatus.className = 'status error';
                reportStatus.textContent = '❌ Ошибка проверки статуса: ' + error.message;
            }
        }

        async function forceUpdateLinks() {
            try {
                addLog('🔄 Принудительное обновление ссылок...');
                
                const response = await fetch('/force_update_links', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ user_id: parseInt(userId) })
                });
                
                const text = await response.text();
                
                // Удаляем лишний текст до первой {
                let cleanText = text;
                const firstBrace = text.indexOf('{');
                if (firstBrace > 0) {
                    cleanText = text.substring(firstBrace);
                }
                
                const result = JSON.parse(cleanText);
                
                if (result.success) {
                    addLog(`✅ ${result.message}`);
                    showStatus('success', `✅ ${result.message}`);
                    setTimeout(checkReportStatus, 1000);
                } else {
                    addLog(`❌ ${result.message}`);
                    showStatus('error', `❌ ${result.message}`);
                }
            } catch (error) {
                addLog(`❌ Ошибка: ${error.message}`);
                showStatus('error', `❌ Ошибка: ${error.message}`);
            }
        }

        async function clearAllData() {
            if (!confirm('⚠️ Удалить ВСЕ данные пользователя?\\n\\nОтчеты останутся, но история публикаций будет очищена.')) {
                return;
            }
            
            try {
                addLog('🗑️ Очистка данных...');
                
                const response = await fetch(`/clear_user_data/${userId}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                
                const text = await response.text();
                
                // Удаляем лишний текст до первой {
                let cleanText = text;
                const firstBrace = text.indexOf('{');
                if (firstBrace > 0) {
                    cleanText = text.substring(firstBrace);
                }
                
                const result = JSON.parse(cleanText);
                
                if (result.success) {
                    showStatus('success', '✅ Данные очищены');
                    addLog('✅ Все данные пользователя очищены');
                    reportStatus.style.display = 'none';
                    reportBtn.disabled = true;
                    reportReady = false;
                    setTimeout(checkReportStatus, 1000);
                } else {
                    showStatus('error', '❌ ' + result.message);
                    addLog('❌ Ошибка: ' + result.message);
                }
            } catch (error) {
                showStatus('error', '❌ Ошибка: ' + error.message);
                addLog('❌ Ошибка: ' + error.message);
            }
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

        function compressImage(file, maxWidth = 600, maxHeight = 600, quality = 0.5) {
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

        // 🔥 ИСПРАВЛЕННАЯ ФУНКЦИЯ С ПОВТОРНЫМИ ПОПЫТКАМИ И ТАЙМАУТОМ
        async function uploadSinglePhoto(file, folderName) {
            const maxRetries = 3;
            let attempt = 0;
            
            while (attempt < maxRetries) {
                try {
                    let compressed;
                    try {
                        compressed = await compressImage(file, 600, 600, 0.5);
                    } catch (e) {
                        addLog(`⚠️ Не удалось сжать ${file.name}, пробуем оригинал`);
                        compressed = file;
                    }
                    
                    addLog(`📤 Загрузка фото ${file.name} (${(compressed.size/1024).toFixed(0)}KB)...`);
                    
                    const formData = new FormData();
                    formData.append('photo', compressed);
                    formData.append('user_id', userId);
                    formData.append('folder_name', folderName);
                    
                    // Добавляем таймаут для fetch
                    const controller = new AbortController();
                    const timeoutId = setTimeout(() => controller.abort(), 60000); // 60 секунд
                    
                    const response = await fetch('/upload_photo', {
                        method: 'POST',
                        body: formData,
                        signal: controller.signal
                    });
                    
                    clearTimeout(timeoutId);
                    
                    const contentType = response.headers.get('content-type');
                    if (!contentType || !contentType.includes('application/json')) {
                        const text = await response.text();
                        addLog(`❌ Сервер вернул не JSON: ${text.substring(0, 100)}`);
                        throw new Error('Невалидный ответ сервера');
                    }
                    
                    const result = await response.json();
                    
                    if (result.success) {
                        addLog(`✅ Фото ${file.name} загружено`);
                        return result.token;
                    } else {
                        throw new Error(result.message || 'Неизвестная ошибка');
                    }
                } catch (error) {
                    attempt++;
                    if (error.name === 'AbortError') {
                        addLog(`⏰ Таймаут загрузки ${file.name}, попытка ${attempt}/${maxRetries}`);
                    } else {
                        addLog(`❌ Ошибка загрузки ${file.name}: ${error.message}, попытка ${attempt}/${maxRetries}`);
                    }
                    
                    if (attempt >= maxRetries) {
                        addLog(`❌ ${file.name}: не удалось загрузить после ${maxRetries} попыток`);
                        return null;
                    }
                    
                    await new Promise(r => setTimeout(r, 2000));
                }
            }
            return null;
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
                .slice(0, 10);
            
            const imageTokens = [];
            let uploadedPhotos = 0;
            const totalPhotos = imageFiles.length;
            
            for (const img of imageFiles) {
                if (isStopped) {
                    break;
                }
                const token = await uploadSinglePhoto(img, folderName);
                if (token) {
                    imageTokens.push(token);
                }
                uploadedPhotos++;
                const photoPercent = Math.round((uploadedPhotos / totalPhotos) * 100);
                addLog(`📸 Прогресс фото: ${uploadedPhotos}/${totalPhotos} (${photoPercent}%)`);
                await new Promise(r => setTimeout(r, 300));
            }
            
            addLog(`📦 Загружено ${imageTokens.length} из ${imageFiles.length} фото`);
            
            return {
                folderName: folderName,
                adText: adText,
                metadataText: metadataText,
                fullText: fullText,
                imageTokens: imageTokens
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
            successCount = 0;
            errorCount = 0;
            reportReady = false;
            reportBtn.disabled = true;
            
            showStatus('info', '⏳ Подготовка данных...');
            progressBar.style.display = 'block';
            progress.style.width = '0%';
            progress.textContent = '0%';
            progress.className = 'progress';
            logDiv.textContent = '';
            queueInfo.style.display = 'block';
            reportStatus.style.display = 'none';
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
            queueInfo.textContent = `📋 В очереди: ${totalFolders} папок | Обработано: 0/${totalFolders}`;
            showStatus('info', `⏳ Подготовка 0/${totalFolders} папок...`);
            
            const results = [];
            
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
                        results.push(`❌ ${folderName}: нет текстового файла`);
                        continue;
                    }
                    
                    if (isStopped) {
                        addLog(`⏹ ОСТАНОВЛЕНО! Пропускаем ${folderName}`);
                        break;
                    }
                    
                    addLog(`📤 Отправка ${i+1}/${totalFolders}: ${folderName} (${folderData.imageTokens.length} фото)`);
                    
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
                        results.push(`✅ ${folderName}: успешно`);
                    } else {
                        errorCount++;
                        addLog(`❌ ${folderName}: ${result.message}`);
                        results.push(`❌ ${folderName}: ${result.message}`);
                    }
                    
                } catch (error) {
                    errorCount++;
                    addLog(`❌ ${folderName}: ошибка - ${error.message}`);
                    results.push(`❌ ${folderName}: ${error.message}`);
                }
                
                processedCount = i + 1;
                await new Promise(r => setTimeout(r, 2000));
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
                addLog(`⏳ Подождите 1-2 минуты для получения ссылок`);
                addLog(`📊 Затем нажмите "Проверить статус"`);
            } else {
                showStatus('warning', `⚠️ Загружено ${successCount} папок, ${errorCount} с ошибками`);
                addLog(`⚠️ Загружено ${successCount} папок, ${errorCount} с ошибками`);
            }
            
            if (results.length > 0) {
                addLog('\\n📋 Детали:');
                results.slice(0, 20).forEach(r => addLog(r));
                if (results.length > 20) {
                    addLog(`... и еще ${results.length - 20} папок`);
                }
            }
            
            if (successCount > 0) {
                addLog(`\\n📊 После ожидания нажмите "Проверить статус"`);
            }
            
            isProcessing = false;
            
            setTimeout(function() {
                addLog('🔄 Автоматическая проверка статуса...');
                checkReportStatus();
            }, 30000);
            
            setTimeout(function() {
                addLog('🧹 Автоочистка данных...');
                fetch('/auto_cleanup/' + userId, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
            }, 300000);
        }
    </script>
</body>
</html>
"""

# ========== МАРШРУТЫ ==========

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # Если пришел POST на корень — обрабатываем как вебхук
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
            logger.error(f"❌ Не удалось загрузить фото {photo.filename}")
            return jsonify({'success': False, 'message': 'Не удалось загрузить фото'}), 500
        
    except ClientDisconnected as e:
        logger.warning(f"⚠️ Клиент разорвал соединение при загрузке фото")
        return jsonify({'success': False, 'message': 'Соединение прервано'}), 400
        
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки фото: {e}")
        import traceback
        traceback.print_exc()
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
                logger.info(f"🗑️ Удалена временная папка: {temp_dir}")
        except Exception as e:
            logger.error(f"⚠️ Ошибка удаления временных файлов: {e}")
        
        return jsonify({
            'success': True,
            'message': 'Процесс остановлен'
        })
        
    except Exception as e:
        logger.error(f"❌ Ошибка остановки: {e}")
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
        image_tokens = folder_data.get('imageTokens', [])
        
        logger.info(f"📦 Получена папка: {folder_name} от пользователя {user_id}")
        logger.info(f"📝 Текст: {len(ad_text)} символов, 🖼️ Фото: {len(image_tokens)}")
        
        success, message = publisher.publish_folder_with_tokens(
            user_id, folder_name, ad_text, metadata_text, image_tokens
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


@app.route('/webhook', methods=['GET', 'POST'])  # ← Добавляем поддержку GET
def webhook():
    # Если это GET-запрос — просто проверяем доступность
    if request.method == 'GET':
        return jsonify({
            "status": "ok",
            "message": "Webhook is ready",
            "webhook_url": os.environ.get("WEBHOOK_URL", "http://91.227.68.137:3000/webhook")
        }), 200
    
    # Основной POST-обработчик
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
            
            logger.info(f"📨 chat_id: {chat_id}, user_id: {user_id}, text: {text}, mid: {message_id}")
            
            if user_id and text:
                # Обработка команды /start
                if text.strip() == '/start':
                    api.send_message(
                        user_id,
                        "🏠 **Главное меню**\n\n"
                        "🌐 **Загрузить папку:**\n"
                        f"🔗 http://91.227.68.137:3000/upload?user_id={user_id}\n\n"
                        "📊 **Получить отчет:**\n"
                        f"🔗 http://91.227.68.137:3000/report/{user_id}\n\n"
                        "⏹ **Остановить публикацию:** `/stop`\n\n"
                        "📋 **Инструкция:**\n"
                        "1. Подготовьте папки с объявлениями\n"
                        "2. Используйте разделитель #изъятая\n"
                        "3. Фото до 10 шт на объявление"
                    )
                    return jsonify({"ok": True}), 200
                
                # Обработка команды /stop
                if text.strip() == '/stop':
                    publisher.stop(user_id)
                    api.send_message(
                        user_id, 
                        "⏹️ **Публикация остановлена!**\n\n"
                        "✅ Все процессы остановлены\n"
                        "🗑️ Временные файлы удалены"
                    )
                    return jsonify({"ok": True}), 200
                
                # 🔥 ОБРАБОТКА КОМАНДЫ /stat
                if text.strip() == '/stat':
                    logger.info(f"📊 Запрос статистики для пользователя {user_id}")
                    try:
                        stats = db.get_stats(user_id)
                        logger.info(f"📊 Получена статистика: {stats}")
                        
                        message = (
                            "📊 **Статистика публикаций**\n\n"
                            f"📦 Всего папок: {stats.get('total', 0)}\n"
                            f"✅ Успешно: {stats.get('success', 0)}\n"
                            f"⏳ В обработке: {stats.get('pending', 0)}\n"
                            f"❌ Ошибок: {stats.get('errors', 0)}\n"
                        )
                        api.send_message(user_id, message)
                        logger.info(f"✅ Статистика отправлена пользователю {user_id}")
                    except Exception as e:
                        logger.error(f"❌ Ошибка получения статистики: {e}")
                        api.send_message(user_id, f"❌ Ошибка получения статистики: {str(e)}")
                    return jsonify({"ok": True}), 200
                
                # Обработка команды /report
                if text.strip() == '/report':
                    api.send_message(user_id, "📊 Создаю отчет...")
                    report_path = report_gen.generate_report(user_id)
                    if report_path:
                        filename = os.path.basename(report_path)
                        download_url = f"http://91.227.68.137:3000/download_report/{user_id}/{filename}"
                        api.send_message(
                            user_id,
                            f"📊 **Отчет создан!**\n\n"
                            f"🔗 [Скачать отчет]({download_url})"
                        )
                    else:
                        api.send_message(user_id, "❌ Нет данных для отчета.")
                    return jsonify({"ok": True}), 200
            
            if chat_id and message_id:
                logger.info(f"📨 Получен ID сообщения: {message_id} для чата {chat_id}")
                if user_id:
                    publisher.handle_message_created(chat_id, message_id, user_id)
                else:
                    publisher.handle_message_created(chat_id, message_id)
                return jsonify({"ok": True}), 200
            
            return jsonify({"ok": True}), 200
        
        if update_type == 'bot_stopped':
            logger.info("📨 Получено событие bot_stopped")
            return jsonify({"ok": True}), 200
        
        logger.info(f"ℹ️ Получен вебхук с update_type: {update_type}")
        return jsonify({"ok": True}), 200
        
    except Exception as e:
        logger.error(f"❌ ОШИБКА В ВЕБХУКЕ: {e}")
        import traceback
        traceback.print_exc()
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
        
        report_gen.mark_report_downloaded(user_id)
        
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
    
    # 🔥 БЕРЁМ URL ИЗ ПЕРЕМЕННОЙ ИЛИ ИСПОЛЬЗУЕМ ЗНАЧЕНИЕ ПО УМОЛЧАНИЮ
    webhook_url = os.environ.get("WEBHOOK_URL", "http://91.227.68.137:3000/webhook")
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
            return f"✅ Вебхук настроен: {webhook_url}\\nПодписка: {payload}"
        else:
            logger.error(f"❌ Ошибка настройки вебхука: {r.status_code} - {r.text}")
            return f"❌ Ошибка: {r.status_code} - {r.text}"
            
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
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


@app.route('/report_status/<int:user_id>')
def report_status(user_id):
    try:
        stats = db.get_stats(user_id)
        
        pending = stats.get('pending', 0)
        success = stats.get('success', 0)
        failed = stats.get('errors', 0)
        total = stats.get('total', 0)
        
        ready = pending == 0 and success > 0
        
        response = jsonify({
            'total': total,
            'pending': pending,
            'success': success,
            'failed': failed,
            'ready': ready,
            'message': '✅ Отчет готов!' if ready else f'⏳ Ожидание {pending} публикаций...'
        })
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response
        
    except Exception as e:
        logger.error(f"❌ Ошибка проверки статуса: {e}")
        response = jsonify({'error': str(e)})
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response, 500


@app.route('/force_update_links', methods=['POST'])
def force_update_links():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        
        if not user_id:
            response = jsonify({'success': False, 'message': 'Нет user_id'})
            response.headers['Content-Type'] = 'application/json; charset=utf-8'
            return response, 400
        
        publications = db.get_publications_with_status(user_id, 'pending')
        
        if not publications:
            response = jsonify({'success': True, 'message': 'Нет pending публикаций'})
            response.headers['Content-Type'] = 'application/json; charset=utf-8'
            return response
        
        updated = 0
        for pub in publications:
            folder_name = pub.get('folder_name')
            metadata = db.get_ad_metadata(user_id, folder_name)
            post_link = metadata.get('post_link')
            
            if post_link:
                db.update_publication_status(user_id, folder_name, 'success')
                updated += 1
                logger.info(f"✅ Принудительно обновлена ссылка для {folder_name}: {post_link}")
        
        response = jsonify({
            'success': True,
            'message': f'Обновлено {updated} публикаций',
            'updated': updated
        })
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response
        
    except Exception as e:
        logger.error(f"❌ Ошибка принудительного обновления: {e}")
        response = jsonify({'success': False, 'message': str(e)})
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response, 500


@app.route('/clear_user_data/<int:user_id>', methods=['POST'])
def clear_user_data(user_id):
    try:
        db.clear_user_data(user_id)
        publisher.clear_diagnostic_log()
        publisher.pending_messages = {}
        
        logger.info(f"🗑️ Данные пользователя {user_id} очищены")
        response = jsonify({
            'success': True,
            'message': f'Данные пользователя {user_id} очищены'
        })
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response
    except Exception as e:
        logger.error(f"❌ Ошибка очистки данных: {e}")
        response = jsonify({'success': False, 'message': str(e)})
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response, 500


@app.route('/auto_cleanup/<int:user_id>', methods=['POST'])
def auto_cleanup(user_id):
    try:
        def delayed_cleanup():
            time.sleep(300)
            logger.info(f"🧹 Автоочистка данных для {user_id} через 5 минут")
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
            logger.info(f"✅ Данные пользователя {user_id} очищены")
        
        threading.Thread(target=delayed_cleanup, daemon=True).start()
        response = jsonify({'success': True, 'message': 'Автоочистка запланирована через 5 минут'})
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response
        
    except Exception as e:
        logger.error(f"❌ Ошибка автоочистки: {e}")
        response = jsonify({'success': False, 'message': str(e)})
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response, 500


@app.route('/webhook_test', methods=['GET'])
def webhook_test():
    response = jsonify({
        'status': 'ok',
        'pending_count': len(publisher.pending_messages),
        'pending_keys': list(publisher.pending_messages.keys())
    })
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    return response


@app.route('/diagnostic/<int:user_id>')
def diagnostic_log(user_id):
    try:
        user_folder = fm.get_user_folder(user_id)
        if not os.path.exists(user_folder):
            return jsonify({'error': 'Пользователь не найден'}), 404
        
        diagnostic_data = publisher.get_diagnostic_log()
        
        user_diagnostic = []
        for entry in diagnostic_data:
            if entry.get('chat_id'):
                publications = db.get_publications(user_id)
                for pub in publications:
                    if pub.get('group_id') == entry.get('chat_id'):
                        user_diagnostic.append(entry)
                        break
        
        if not user_diagnostic:
            user_diagnostic = diagnostic_data[-20:]
        
        response = jsonify({
            'user_id': user_id,
            'total_entries': len(diagnostic_data),
            'user_entries': len(user_diagnostic),
            'diagnostic': user_diagnostic[-50:]
        })
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения диагностики: {e}")
        response = jsonify({'error': str(e)})
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response, 500


@app.route('/diagnostic/clear', methods=['POST'])
def clear_diagnostic_log():
    try:
        publisher.clear_diagnostic_log()
        response = jsonify({'success': True, 'message': 'Диагностический журнал очищен'})
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response
    except Exception as e:
        response = jsonify({'success': False, 'message': str(e)})
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response, 500


@app.route('/diagnostic/last')
def diagnostic_last():
    try:
        diagnostic_data = publisher.get_diagnostic_log()
        if diagnostic_data:
            response = jsonify({
                'success': True,
                'last_entry': diagnostic_data[-1]
            })
        else:
            response = jsonify({
                'success': True,
                'message': 'Нет диагностических записей',
                'last_entry': None
            })
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response
    except Exception as e:
        response = jsonify({'success': False, 'message': str(e)})
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response, 500


@app.errorhandler(ClientDisconnected)
def handle_client_disconnected(e):
    logger.warning(f"⚠️ Клиент разорвал соединение: {e}")
    return jsonify({'success': False, 'message': 'Соединение прервано'}), 400


@app.errorhandler(Exception)
def handle_all_exceptions(error):
    logger.error(f"Критическая ошибка обработки запроса: {error}", exc_info=True)
    response = jsonify({
        'success': False,
        'message': 'Внутренняя ошибка сервера',
        'details': str(error)
    })
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    return response, 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    
    if TOKEN:
        logger.info(f"✅ Токен найден (первые 10): {TOKEN[:10]}...")
        
        # 🔥 БЕРЁМ URL ИЗ ПЕРЕМЕННОЙ ОКРУЖЕНИЯ
        webhook_url = os.environ.get(
            "WEBHOOK_URL", 
            "http://91.227.68.137:3000/webhook"  # значение по умолчанию
        )
        
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
            logger.warning(f"⚠️ Ошибка настройки вебхука при запуске: {e}")
    else:
        logger.error("❌ Токен не найден! Вебхук не настроен.")
    
    app.run(host='0.0.0.0', port=port, threaded=True)
