# app.py - БЕЗ REDIS

from flask import Flask, request, jsonify, render_template_string, send_file
import os
import logging
import json
import requests
import traceback
import time
import base64
from datetime import datetime
from modules import Database, FileManager
from modules.report_generator import ReportGenerator
from modules.publisher import Publisher

# ========== ИНИЦИАЛИЗАЦИЯ ==========
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24).hex())
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024

# ========== ЛОГИРОВАНИЕ ==========
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== КОНФИГУРАЦИЯ ==========
TOKEN = os.environ.get("MAX_TOKEN") or os.environ.get("MAX_BOT_TOKEN") or os.environ.get("TOKEN")
DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
MAX_API_URL = os.environ.get("MAX_API_URL", "https://platform-api2.max.ru")

if not TOKEN:
    logger.error("❌ ТОКЕН НЕ НАЙДЕН!")

# ========== ИНИЦИАЛИЗАЦИЯ ==========
db = Database()
fm = FileManager(DATA_DIR)
report_gen = ReportGenerator(fm, db)

class APIClient:
    def __init__(self):
        self.token = TOKEN
        self.base_url = "https://platform-api2.max.ru"

api = APIClient()
publisher = Publisher(api, fm, db)

# ========== UPLOAD_PAGE ==========
UPLOAD_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Загрузка объявлений</title>
    <style>
        body { font-family: Arial; max-width: 800px; margin: 50px auto; padding: 20px; background: #f5f5f5; }
        .container { background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1 { color: #333; }
        .drop-zone { border: 2px dashed #007bff; padding: 40px; margin: 20px 0; border-radius: 10px; background: #f8f9fa; text-align: center; cursor: pointer; }
        .drop-zone:hover { background: #e3f2fd; }
        .drop-zone.dragover { background: #d4edda; border-color: #28a745; }
        input[type="file"] { display: none; }
        .btn { padding: 12px 30px; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; font-weight: bold; }
        .btn-success { background: #28a745; color: white; }
        .btn-success:hover { background: #218838; }
        .btn-danger { background: #dc3545; color: white; }
        .btn-danger:hover { background: #c82333; }
        .btn-warning { background: #ffc107; color: #333; }
        .btn-warning:hover { background: #e0a800; }
        .status { margin-top: 20px; padding: 15px; border-radius: 5px; display: none; }
        .status.success { background: #d4edda; color: #155724; display: block; }
        .status.error { background: #f8d7da; color: #721c24; display: block; }
        .status.info { background: #d1ecf1; color: #0c5460; display: block; }
        .progress-bar { width: 100%; height: 25px; background: #e9ecef; border-radius: 10px; overflow: hidden; margin: 10px 0; display: none; }
        .progress-bar .progress { height: 100%; background: linear-gradient(90deg, #28a745, #20c997); transition: width 0.3s; width: 0%; display: flex; align-items: center; justify-content: center; color: white; font-size: 12px; }
        #log { background: #1e1e1e; color: #d4d4d4; padding: 15px; border-radius: 5px; font-family: monospace; font-size: 12px; max-height: 300px; overflow-y: auto; margin: 20px 0; display: none; white-space: pre-wrap; }
        .file-list li { background: #f8f9fa; padding: 10px; margin: 5px 0; border-radius: 5px; border-left: 3px solid #007bff; display: flex; justify-content: space-between; }
        .settings-section { background: #e7f5ff; padding: 15px; border-radius: 10px; margin: 15px 0; }
        .settings-section label { display: inline-block; margin-right: 15px; font-weight: bold; }
        .settings-section input[type="number"] { width: 60px; padding: 5px; border: 1px solid #ccc; border-radius: 5px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📤 Загрузка объявлений</h1>
        
        <div class="settings-section">
            <label>📸 Максимум фото: <input type="number" id="maxPhotos" value="6" min="1" max="10"></label>
        </div>
        
        <div class="drop-zone" id="dropZone">
            <span style="font-size:48px;">📂</span>
            <p><strong>Перетащите головную папку сюда</strong></p>
            <button class="btn btn-success" onclick="document.getElementById('folderInput').click()">Выбрать папку</button>
            <input type="file" id="folderInput" webkitdirectory multiple>
        </div>
        
        <div id="fileList" style="display:none;">
            <div id="selectedInfo"></div>
            <ul class="file-list" id="fileListContent"></ul>
            <button class="btn btn-success" onclick="uploadFolder()">🚀 Загрузить</button>
            <button class="btn btn-danger" onclick="clearFiles()">🗑️ Очистить</button>
        </div>
        
        <div class="progress-bar" id="progressBar"><div class="progress" id="progress">0%</div></div>
        <div id="status" class="status"></div>
        <div id="log"></div>
        
        <div style="margin-top:20px;text-align:center;">
            <button class="btn btn-success" onclick="getReport()">📊 Скачать отчет</button>
        </div>
    </div>

    <script>
        const userId = new URLSearchParams(window.location.search).get('user_id') || 151296248;
        let selectedFiles = [];
        let isProcessing = false;
        let totalFolders = 0;
        
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
            let pending = 0;
            
            function processEntry(entry, path) {
                if (entry.isDirectory) {
                    const reader = entry.createReader();
                    reader.readEntries((entries) => {
                        for (let e of entries) {
                            processEntry(e, path + entry.name + '/');
                        }
                    });
                } else {
                    entry.file((file) => {
                        file.webkitRelativePath = path + file.name;
                        files.push(file);
                        pending--;
                        if (pending === 0) {
                            selectedFiles = files;
                            displayFiles(selectedFiles);
                        }
                    });
                }
            }
            
            for (let item of items) {
                if (item.kind === 'file') {
                    const entry = item.webkitGetAsEntry();
                    if (entry) {
                        pending++;
                        processEntry(entry, '');
                    }
                }
            }
            
            if (pending === 0 && files.length > 0) {
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

        function compressImage(file, maxWidth = 1920, maxHeight = 1920, quality = 0.85) {
            return new Promise((resolve, reject) => {
                if (file.size > 20 * 1024 * 1024) {
                    reject(new Error('Файл слишком большой'));
                    return;
                }
                const reader = new FileReader();
                reader.onload = function(e) {
                    const img = new Image();
                    img.onload = function() {
                        let width = img.width, height = img.height;
                        if (width > maxWidth) { height = (height * maxWidth) / width; width = maxWidth; }
                        if (height > maxHeight) { width = (width * maxHeight) / height; height = maxHeight; }
                        const canvas = document.createElement('canvas');
                        canvas.width = width; canvas.height = height;
                        const ctx = canvas.getContext('2d');
                        ctx.drawImage(img, 0, 0, width, height);
                        canvas.toBlob((blob) => {
                            if (blob) {
                                resolve(new File([blob], file.name, { type: 'image/jpeg' }));
                            } else {
                                reject(new Error('Не удалось сжать'));
                            }
                        }, 'image/jpeg', quality);
                    };
                    img.onerror = reject;
                    img.src = e.target.result;
                };
                reader.onerror = reject;
                reader.readAsDataURL(file);
            });
        }

        function displayFiles(files) {
            fileListContent.innerHTML = '';
            const folders = new Set();
            files.forEach(f => {
                const parts = f.webkitRelativePath.split('/');
                if (parts.length >= 2) folders.add(parts[0]);
            });
            const sortedFolders = Array.from(folders).sort();
            sortedFolders.forEach(folder => {
                const li = document.createElement('li');
                const count = files.filter(f => f.webkitRelativePath.startsWith(folder + '/')).length;
                li.innerHTML = `<span>📁 ${folder}</span><span>${count} файлов</span>`;
                fileListContent.appendChild(li);
            });
            selectedInfo.textContent = `✅ Найдено ${sortedFolders.length} папок, ${files.length} файлов`;
            fileList.style.display = 'block';
            totalFolders = sortedFolders.length;
        }

        function addLog(msg) {
            logDiv.style.display = 'block';
            logDiv.textContent += msg + '\\n';
            logDiv.scrollTop = logDiv.scrollHeight;
        }

        function showStatus(type, msg) {
            statusDiv.className = 'status ' + type;
            statusDiv.textContent = msg;
            statusDiv.style.display = 'block';
        }

        function getReport() { window.open(`/report/${userId}`, '_blank'); }

        function clearFiles() {
            selectedFiles = [];
            fileList.style.display = 'none';
            statusDiv.style.display = 'none';
            progressBar.style.display = 'none';
            logDiv.style.display = 'none';
            progress.style.width = '0%';
            folderInput.value = '';
        }

        async function uploadFolder() {
            if (selectedFiles.length === 0) {
                showStatus('error', '❌ Выберите папку');
                return;
            }
            if (isProcessing) {
                addLog('⚠️ Уже выполняется');
                return;
            }
            
            isProcessing = true;
            const maxPhotos = parseInt(document.getElementById('maxPhotos').value) || 6;
            
            const folders = {};
            selectedFiles.forEach(f => {
                const parts = f.webkitRelativePath.split('/');
                if (parts.length >= 2) {
                    const folderName = parts[0];
                    if (!fold
