# app.py - С ВСТРОЕННЫМ CORS И ПОЛНЫМ ИНТЕРФЕЙСОМ

from flask import Flask, request, jsonify, render_template_string, send_file
import os
import logging
import json
import requests
import traceback
import time
import base64
import gc
import urllib3
from datetime import datetime

# ========== ИНИЦИАЛИЗАЦИЯ ==========
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24).hex())
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

# ========== ВСТРОЕННЫЙ CORS (без внешних библиотек) ==========
@app.after_request
def after_request(response):
    """Добавляет CORS заголовки ко всем ответам"""
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,Accept')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response

# ========== ЛОГИРОВАНИЕ ==========
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== ВСЕ ПЕРЕМЕННЫЕ ИЗ ОКРУЖЕНИЯ ==========
TOKEN = os.environ.get("MAX_TOKEN") or os.environ.get("MAX_BOT_TOKEN") or os.environ.get("TOKEN")
DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
MAX_API_URL = os.environ.get("MAX_API_URL", "https://platform-api2.max.ru")
BASE_URL = os.environ.get("BASE_URL")

if not TOKEN:
    logger.error("❌ ТОКЕН НЕ НАЙДЕН!")
if not BASE_URL:
    logger.warning("⚠️ BASE_URL не установлен! Вебхук может не работать.")

# ========== SSL - ВСЕГДА ОТКЛЮЧЕН ==========
SSL_VERIFY = False
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger.warning("⚠️ SSL проверка ОТКЛЮЧЕНА (для MAX API)")

# ========== ИНИЦИАЛИЗАЦИЯ МОДУЛЕЙ ==========
db = None
fm = None
report_gen = None
publisher = None

def init_app():
    """Инициализация модулей приложения"""
    global db, fm, report_gen, publisher
    
    try:
        from modules import Database, FileManager
        from modules.report_generator import ReportGenerator
        from modules.publisher import Publisher
        
        logger.info("🔄 Инициализация приложения...")
        db = Database()
        fm = FileManager(DATA_DIR)
        report_gen = ReportGenerator(fm, db)
        
        class APIClient:
            def __init__(self):
                self.token = TOKEN
                self.base_url = MAX_API_URL
                self.verify = False
        
        publisher = Publisher(APIClient(), fm, db)
        logger.info("✅ Приложение инициализировано")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации: {e}")
        logger.error(traceback.format_exc())
        return False

# ========== UPLOAD_PAGE HTML ==========
UPLOAD_PAGE = '''
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MAX Bot - Загрузка объявлений</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1000px;
            margin: 0 auto;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
            padding: 40px;
        }
        
        .header {
            text-align: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 2px solid #f0f0f0;
        }
        
        .header h1 {
            font-size: 32px;
            color: #333;
            margin-bottom: 10px;
        }
        
        .header .subtitle {
            color: #666;
            font-size: 16px;
        }
        
        .header .badge {
            display: inline-block;
            background: #667eea;
            color: white;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            margin-top: 10px;
        }
        
        .instructions {
            background: #fff3cd;
            padding: 20px;
            border-radius: 12px;
            margin: 20px 0;
            border-left: 4px solid #ffc107;
        }
        
        .instructions strong {
            color: #856404;
        }
        
        .instructions ul {
            margin: 10px 0 0 20px;
            color: #856404;
        }
        
        .instructions ul li {
            margin: 5px 0;
        }
        
        .settings-section {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 12px;
            margin: 20px 0;
            border: 1px solid #e9ecef;
        }
        
        .settings-section h4 {
            margin-bottom: 15px;
            color: #333;
        }
        
        .settings-row {
            display: flex;
            flex-wrap: wrap;
            gap: 20px;
            align-items: center;
        }
        
        .settings-row label {
            display: flex;
            align-items: center;
            gap: 10px;
            font-weight: 500;
            color: #555;
        }
        
        .settings-row input[type="number"] {
            width: 70px;
            padding: 8px 12px;
            border: 2px solid #dee2e6;
            border-radius: 8px;
            font-size: 14px;
            transition: border-color 0.3s;
        }
        
        .settings-row input[type="number"]:focus {
            outline: none;
            border-color: #667eea;
        }
        
        .drop-zone {
            border: 3px dashed #667eea;
            padding: 50px 20px;
            margin: 20px 0;
            border-radius: 16px;
            background: #f8f9ff;
            text-align: center;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        
        .drop-zone:hover {
            background: #f0f2ff;
            border-color: #764ba2;
        }
        
        .drop-zone.dragover {
            background: #e8f5e9;
            border-color: #4caf50;
            transform: scale(1.02);
        }
        
        .drop-zone .icon {
            font-size: 64px;
            margin-bottom: 15px;
        }
        
        .drop-zone p {
            color: #666;
            font-size: 18px;
            margin: 10px 0;
        }
        
        .drop-zone .hint {
            color: #999;
            font-size: 14px;
        }
        
        input[type="file"] {
            display: none;
        }
        
        .btn {
            padding: 12px 30px;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            font-size: 16px;
            font-weight: 600;
            transition: all 0.3s ease;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }
        
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 20px rgba(0,0,0,0.15);
        }
        
        .btn:active {
            transform: translateY(0);
        }
        
        .btn-primary {
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
        }
        
        .btn-success {
            background: linear-gradient(135deg, #43a047, #66bb6a);
            color: white;
        }
        
        .btn-danger {
            background: linear-gradient(135deg, #e53935, #ef5350);
            color: white;
        }
        
        .btn-warning {
            background: linear-gradient(135deg, #f57c00, #ffa726);
            color: white;
        }
        
        .btn-info {
            background: linear-gradient(135deg, #00838f, #26c6da);
            color: white;
        }
        
        .btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }
        
        .file-list-section {
            margin: 20px 0;
            display: none;
        }
        
        .file-list-section.visible {
            display: block;
        }
        
        .selected-info {
            background: #e3f2fd;
            padding: 12px 20px;
            border-radius: 10px;
            margin: 10px 0;
            border-left: 4px solid #2196f3;
            color: #0d47a1;
            font-weight: 500;
        }
        
        .queue-info {
            background: #f3e5f5;
            padding: 12px 20px;
            border-radius: 10px;
            margin: 10px 0;
            border-left: 4px solid #9c27b0;
            color: #4a148c;
        }
        
        .file-list {
            list-style: none;
            padding: 0;
            margin: 15px 0;
            max-height: 400px;
            overflow-y: auto;
        }
        
        .file-list li {
            background: #f8f9fa;
            padding: 12px 18px;
            margin: 6px 0;
            border-radius: 10px;
            border-left: 4px solid #667eea;
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: background 0.3s;
        }
        
        .file-list li:hover {
            background: #e9ecef;
        }
        
        .file-list li .folder-name {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .file-list li .folder-name .emoji {
            font-size: 20px;
        }
        
        .file-list li .folder-name strong {
            color: #333;
        }
        
        .file-list li .file-count {
            background: #667eea;
            color: white;
            padding: 2px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        
        .file-list li .status-badge {
            font-size: 12px;
            padding: 4px 12px;
            border-radius: 20px;
            font-weight: 600;
            margin-left: 10px;
        }
        
        .file-list li .status-badge.pending {
            background: #ffd54f;
            color: #f57f17;
        }
        
        .file-list li .status-badge.processing {
            background: #64b5f6;
            color: #0d47a1;
            animation: pulse 1s infinite;
        }
        
        .file-list li .status-badge.done {
            background: #81c784;
            color: #1b5e20;
        }
        
        .file-list li .status-badge.error {
            background: #ef9a9a;
            color: #b71c1c;
        }
        
        @keyframes pulse {
            0% { opacity: 1; }
            50% { opacity: 0.5; }
            100% { opacity: 1; }
        }
        
        .button-group {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            margin: 15px 0;
        }
        
        .progress-section {
            margin: 20px 0;
            display: none;
        }
        
        .progress-section.visible {
            display: block;
        }
        
        .progress-bar {
            width: 100%;
            height: 30px;
            background: #e9ecef;
            border-radius: 15px;
            overflow: hidden;
            position: relative;
        }
        
        .progress-bar .progress {
            height: 100%;
            background: linear-gradient(90deg, #667eea, #764ba2);
            transition: width 0.5s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-size: 13px;
            font-weight: 600;
            width: 0%;
        }
        
        .progress-text {
            text-align: center;
            margin-top: 10px;
            color: #666;
            font-size: 14px;
        }
        
        .status {
            margin: 20px 0;
            padding: 15px 20px;
            border-radius: 12px;
            display: none;
            font-weight: 500;
        }
        
        .status.visible {
            display: block;
        }
        
        .status.success {
            background: #e8f5e9;
            color: #1b5e20;
            border-left: 4px solid #4caf50;
        }
        
        .status.error {
            background: #ffebee;
            color: #b71c1c;
            border-left: 4px solid #f44336;
        }
        
        .status.info {
            background: #e3f2fd;
            color: #0d47a1;
            border-left: 4px solid #2196f3;
        }
        
        .status.warning {
            background: #fff3e0;
            color: #e65100;
            border-left: 4px solid #ff9800;
        }
        
        .log-section {
            margin: 20px 0;
            display: none;
        }
        
        .log-section.visible {
            display: block;
        }
        
        .log-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }
        
        .log-header h4 {
            color: #333;
        }
        
        .log-header .log-count {
            background: #333;
            color: white;
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 12px;
        }
        
        #log {
            background: #1a1a2e;
            color: #e0e0e0;
            padding: 20px;
            border-radius: 12px;
            font-family: 'Courier New', monospace;
            font-size: 13px;
            max-height: 350px;
            overflow-y: auto;
            white-space: pre-wrap;
            line-height: 1.6;
        }
        
        #log::-webkit-scrollbar {
            width: 8px;
        }
        
        #log::-webkit-scrollbar-track {
            background: #2a2a3e;
            border-radius: 4px;
        }
        
        #log::-webkit-scrollbar-thumb {
            background: #667eea;
            border-radius: 4px;
        }
        
        .log-entry {
            padding: 2px 0;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }
        
        .log-entry .time {
            color: #888;
            margin-right: 10px;
        }
        
        .log-entry .emoji {
            margin-right: 8px;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }
        
        .stat-card {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 12px;
            text-align: center;
            border: 1px solid #e9ecef;
            transition: transform 0.3s;
        }
        
        .stat-card:hover {
            transform: translateY(-3px);
        }
        
        .stat-card .number {
            font-size: 32px;
            font-weight: 700;
            color: #333;
        }
        
        .stat-card .label {
            color: #888;
            font-size: 14px;
            margin-top: 5px;
        }
        
        .stat-card.success .number {
            color: #43a047;
        }
        
        .stat-card.error .number {
            color: #e53935;
        }
        
        .stat-card.total .number {
            color: #667eea;
        }
        
        .report-section {
            background: #f8f9fa;
            padding: 25px;
            border-radius: 12px;
            text-align: center;
            margin: 20px 0;
            border: 1px solid #e9ecef;
        }
        
        .report-section p {
            margin-top: 10px;
            color: #888;
            font-size: 14px;
        }
        
        .footer {
            text-align: center;
            margin-top: 30px;
            padding-top: 20px;
            border-top: 2px solid #f0f0f0;
            color: #999;
            font-size: 14px;
        }
        
        .footer .heart {
            color: #e53935;
        }
        
        @media (max-width: 768px) {
            .container {
                padding: 20px;
                border-radius: 12px;
            }
            
            .header h1 {
                font-size: 24px;
            }
            
            .settings-row {
                flex-direction: column;
                align-items: flex-start;
            }
            
            .button-group {
                flex-direction: column;
            }
            
            .button-group .btn {
                width: 100%;
                justify-content: center;
            }
            
            .stats-grid {
                grid-template-columns: 1fr 1fr;
            }
            
            .drop-zone {
                padding: 30px 15px;
            }
            
            .drop-zone .icon {
                font-size: 40px;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <h1>📤 Загрузка объявлений</h1>
            <p class="subtitle">MAX Bot — удобная публикация в чаты</p>
            <span class="badge">⚡ Версия 2.0</span>
        </div>
        
        <!-- Instructions -->
        <div class="instructions">
            <strong>📌 Как подготовить папки:</strong>
            <ul>
                <li>Создайте головную папку с подпапками для каждого объявления</li>
                <li>В каждой подпапке разместите <code>info.txt</code> и фото (до 10 шт)</li>
                <li>Используйте разделитель <code>#изъятая</code> для метаданных</li>
                <li>В названии папки укажите chat_id (например: <code>Товары - 1234567890</code>)</li>
                <li>Перетащите головную папку в поле ниже</li>
            </ul>
        </div>
        
        <!-- Settings -->
        <div class="settings-section">
            <h4>⚙️ Настройки публикации</h4>
            <div class="settings-row">
                <label>
                    📸 Максимум фото:
                    <input type="number" id="maxPhotos" value="6" min="1" max="10">
                </label>
                <label>
                    ⏱️ Задержка между папками (сек):
                    <input type="number" id="delayBetween" value="3" min="1" max="30">
                </label>
            </div>
        </div>
        
        <!-- Drop Zone -->
        <div class="drop-zone" id="dropZone">
            <div class="icon">📂</div>
            <p><strong>Перетащите головную папку сюда</strong></p>
            <p class="hint">или нажмите кнопку ниже для выбора</p>
            <br>
            <button class="btn btn-primary" onclick="document.getElementById('folderInput').click()">📁 Выбрать папку</button>
            <input type="file" id="folderInput" webkitdirectory multiple>
        </div>
        
        <!-- File List -->
        <div class="file-list-section" id="fileListSection">
            <div class="selected-info" id="selectedInfo"></div>
            <div class="queue-info">
                <strong>📋 Очередь:</strong> <span id="queueStatus">Ожидание</span>
            </div>
            <ul class="file-list" id="fileListContent"></ul>
            <div class="button-group">
                <button class="btn btn-success" onclick="uploadFolder()" id="uploadBtn">
                    🚀 Начать загрузку
                </button>
                <button class="btn btn-danger" onclick="clearFiles()">
                    🗑️ Очистить всё
                </button>
            </div>
        </div>
        
        <!-- Progress -->
        <div class="progress-section" id="progressSection">
            <div class="progress-bar">
                <div class="progress" id="progress">0%</div>
            </div>
            <div class="progress-text" id="progressText">Ожидание начала...</div>
        </div>
        
        <!-- Status -->
        <div class="status" id="status"></div>
        
        <!-- Log -->
        <div class="log-section" id="logSection">
            <div class="log-header">
                <h4>📋 Лог операций</h4>
                <span class="log-count" id="logCount">0 записей</span>
            </div>
            <div id="log"></div>
        </div>
        
        <!-- Stats -->
        <div class="stats-grid" id="statsGrid">
            <div class="stat-card total">
                <div class="number" id="statTotal">0</div>
                <div class="label">📊 Всего публикаций</div>
            </div>
            <div class="stat-card success">
                <div class="number" id="statSuccess">0</div>
                <div class="label">✅ Успешно</div>
            </div>
            <div class="stat-card error">
                <div class="number" id="statErrors">0</div>
                <div class="label">❌ Ошибок</div>
            </div>
        </div>
        
        <!-- Report -->
        <div class="report-section">
            <button class="btn btn-info" onclick="getReport()">📊 Скачать отчет</button>
            <button class="btn btn-warning" onclick="loadStats()">🔄 Обновить статистику</button>
            <p>После завершения публикации всех папок</p>
        </div>
        
        <!-- Footer -->
        <div class="footer">
            Сделано с <span class="heart">❤️</span> для MAX Bot | SQLite
        </div>
    </div>

    <script>
        const userId = new URLSearchParams(window.location.search).get('user_id') || 151296248;
        let selectedFiles = [];
        let isProcessing = false;
        let folderQueue = [];
        let totalFolders = 0;
        let logEntries = 0;

        // Загрузка статистики при старте
        window.onload = function() {
            loadStats();
        };

        // Загрузка статистики
        function loadStats() {
            fetch('/stats/' + userId)
                .then(res => res.json())
                .then(data => {
                    document.getElementById('statTotal').textContent = data.total || 0;
                    document.getElementById('statSuccess').textContent = data.success || 0;
                    document.getElementById('statErrors').textContent = data.errors || 0;
                })
                .catch(err => console.error('Ошибка загрузки статистики:', err));
        }

        // Рекурсивное чтение директории
        function readDirectoryRecursive(entry, path, files, callback) {
            if (entry.isDirectory) {
                const reader = entry.createReader();
                let allEntries = [];
                
                function readEntries() {
                    reader.readEntries((entries) => {
                        if (entries.length === 0) {
                            let pending = allEntries.length;
                            if (pending === 0) { callback(); return; }
                            
                            allEntries.forEach(e => {
                                if (e.isDirectory) {
                                    readDirectoryRecursive(e, path + e.name + '/', files, () => {
                                        pending--;
                                        if (pending === 0) callback();
                                    });
                                } else {
                                    e.file((file) => {
                                        file.webkitRelativePath = path + file.name;
                                        files.push(file);
                                        pending--;
                                        if (pending === 0) callback();
                                    });
                                }
                            });
                        } else {
                            allEntries = allEntries.concat(entries);
                            readEntries();
                        }
                    });
                }
                readEntries();
            } else {
                entry.file((file) => {
                    file.webkitRelativePath = path + file.name;
                    files.push(file);
                    callback();
                });
            }
        }

        // Drag & Drop
        const dropZone = document.getElementById('dropZone');
        const folderInput = document.getElementById('folderInput');

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
            let pending = 0;
            
            for (let item of items) {
                if (item.kind === 'file') {
                    const entry = item.webkitGetAsEntry();
                    if (entry) {
                        pending++;
                        readDirectoryRecursive(entry, '', files, () => {
                            pending--;
                            if (pending === 0) {
                                selectedFiles = files;
                                displayFiles(selectedFiles);
                            }
                        });
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

        // Сжатие изображения
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
                        let w = img.width;
                        let h = img.height;
                        
                        if (w > maxWidth) {
                            h = (h * maxWidth) / w;
                            w = maxWidth;
                        }
                        if (h > maxHeight) {
                            w = (w * maxHeight) / h;
                            h = maxHeight;
                        }
                        
                        const canvas = document.createElement('canvas');
                        canvas.width = w;
                        canvas.height = h;
                        const ctx = canvas.getContext('2d');
                        ctx.drawImage(img, 0, 0, w, h);
                        
                        canvas.toBlob((blob) => {
                            if (blob) {
                                resolve(new File([blob], file.name, {
                                    type: 'image/jpeg',
                                    lastModified: Date.now()
                                }));
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

        // Отображение файлов
        function displayFiles(files) {
            const container = document.getElementById('fileListContent');
            container.innerHTML = '';
            
            const folders = new Map();
            
            files.forEach(f => {
                const parts = f.webkitRelativePath.split('/');
                if (parts.length >= 2) {
                    const root = parts[0];
                    const sub = parts.length > 2 ? parts.slice(1, -1).join('/') : 'root';
                    const key = root + '/' + sub;
                    
                    if (!folders.has(key)) {
                        folders.set(key, {
                            root: root,
                            sub: sub,
                            display: sub === 'root' ? root : root + '/' + sub,
                            count: 0,
                            files: []
                        });
                    }
                    folders.get(key).count++;
                    folders.get(key).files.push(f);
                }
            });
            
            const sorted = Array.from(folders.values()).sort((a, b) => a.display.localeCompare(b.display));
            
            folderQueue = sorted.map(f => ({
                name: f.display,
                status: 'pending',
                count: f.count,
                files: f.files
            }));
            
            sorted.forEach(folder => {
                const li = document.createElement('li');
                const isSub = folder.sub !== 'root';
                li.innerHTML = `
                    <div class="folder-name">
                        <span class="emoji">${isSub ? '📂' : '📁'}</span>
                        <strong>${folder.display}</strong>
                    </div>
                    <div>
                        <span class="file-count">${folder.count} файлов</span>
                        <span class="status-badge pending" id="st-${folder.display.replace(/[\/\\]/g,'-')}">⏳ Ожидание</span>
                    </div>
                `;
                li.style.borderLeftColor = isSub ? '#4caf50' : '#667eea';
                container.appendChild(li);
            });
            
            document.getElementById('selectedInfo').textContent = `✅ Найдено ${sorted.length} папок, ${files.length} файлов`;
            document.getElementById('fileListSection').classList.add('visible');
            updateQueueStatus();
            totalFolders = sorted.length;
            
            // Показываем кнопку загрузки
            document.getElementById('uploadBtn').disabled = false;
        }

        // Обновление статуса очереди
        function updateQueueStatus() {
            const done = folderQueue.filter(f => f.status === 'done').length;
            const errors = folderQueue.filter(f => f.status === 'error').length;
            const processing = folderQueue.filter(f => f.status === 'processing').length;
            const total = folderQueue.length;
            
            let status = isProcessing ? `🔄 Обработка` : `📋 Готово`;
            status += ` ${done + errors}/${total}`;
            if (processing > 0) status += ` (⏳${processing} в процессе)`;
            if (errors > 0) status += ` ⚠️${errors} ошибок`;
            
            document.getElementById('queueStatus').textContent = status;
        }

        // Обновление статуса папки
        function updateFolderStatus(name, status) {
            const idx = folderQueue.findIndex(f => f.name === name);
            if (idx !== -1) {
                folderQueue[idx].status = status;
                updateQueueStatus();
                
                const badge = document.getElementById('st-' + name.replace(/[\/\\]/g,'-'));
                if (badge) {
                    badge.className = 'status-badge ' + status;
                    const labels = {
                        'pending': '⏳ Ожидание',
                        'processing': '🔄 Обработка...',
                        'done': '✅ Готово',
                        'error': '❌ Ошибка'
                    };
                    badge.textContent = labels[status] || status;
                }
            }
        }

        // Добавление в лог
        function addLog(msg, emoji = '📝') {
            const log = document.getElementById('log');
            log.style.display = 'block';
            
            const time = new Date().toLocaleTimeString();
            const entry = document.createElement('div');
            entry.className = 'log-entry';
            entry.innerHTML = `<span class="time">[${time}]</span><span class="emoji">${emoji}</span>${msg}`;
            log.appendChild(entry);
            
            log.scrollTop = log.scrollHeight;
            logEntries++;
            document.getElementById('logCount').textContent = logEntries + ' записей';
            document.getElementById('logSection').classList.add('visible');
        }

        // Показ статуса
        function showStatus(type, msg) {
            const s = document.getElementById('status');
            s.className = 'status ' + type + ' visible';
            s.textContent = msg;
        }

        // Получение отчета
        function getReport() {
            window.open('/report/' + userId, '_blank');
        }

        // Очистка
        function clearFiles() {
            if (isProcessing) {
                if (!confirm('Вы уверены, что хотите остановить загрузку?')) return;
            }
            
            selectedFiles = [];
            folderQueue = [];
            document.getElementById('fileListSection').classList.remove('visible');
            document.getElementById('status').className = 'status';
            document.getElementById('status').style.display = 'none';
            document.getElementById('progressSection').classList.remove('visible');
            document.getElementById('progress').style.width = '0%';
            document.getElementById('progress').textContent = '0%';
            document.getElementById('progressText').textContent = 'Ожидание начала...';
            document.getElementById('logSection').classList.remove('visible');
            document.getElementById('log').innerHTML = '';
            document.getElementById('log').style.display = 'none';
            document.getElementById('logCount').textContent = '0 записей';
            logEntries = 0;
            folderInput.value = '';
            isProcessing = false;
            document.getElementById('uploadBtn').disabled = false;
        }

        // Основная функция загрузки
        async function uploadFolder() {
            if (selectedFiles.length === 0) {
                showStatus('error', '❌ Выберите папку для загрузки');
                return;
            }
            
            if (isProcessing) {
                addLog('⚠️ Загрузка уже выполняется', '⚠️');
                return;
            }
            
            isProcessing = true;
            document.getElementById('uploadBtn').disabled = true;
            
            const maxPhotos = parseInt(document.getElementById('maxPhotos').value) || 6;
            const delay = parseInt(document.getElementById('delayBetween').value) || 3;
            
            // Показываем прогресс
            document.getElementById('progressSection').classList.add('visible');
            document.getElementById('progress').style.width = '0%';
            document.getElementById('progress').textContent = '0%';
            document.getElementById('progressText').textContent = 'Подготовка к загрузке...';
            
            // Очищаем лог
            document.getElementById('log').innerHTML = '';
            logEntries = 0;
            document.getElementById('logCount').textContent = '0 записей';
            
            addLog('🚀 Начинаем загрузку ' + totalFolders + ' папок', '🚀');
            addLog(`📸 Максимум фото: ${maxPhotos}, задержка: ${delay} сек`, '⚙️');
            
            let processed = 0;
            let totalImages = 0;
            let errors = 0;
            let successCount = 0;
            
            for (let idx = 0; idx < folderQueue.length; idx++) {
                const folder = folderQueue[idx];
                const name = folder.name;
                const files = folder.files;
                
                updateFolderStatus(name, 'processing');
                addLog(`📂 [${idx+1}/${totalFolders}] Обработка: ${name}`, '📂');
                
                // Находим info.txt и изображения
                let infoFile = null;
                let imageFiles = [];
                
                for (const f of files) {
                    const fn = f.name.toLowerCase();
                    if (fn.endsWith('.txt') && fn.includes('info')) {
                        infoFile = f;
                    } else if (fn.match(/\.(jpg|jpeg|png|gif|bmp|webp)$/)) {
                        if (f.size > 5 * 1024 * 1024) {
                            addLog(`⚠️ ${f.name} слишком большой, пропускаем`, '⚠️');
                            continue;
                        }
                        imageFiles.push(f);
                    }
                }
                
                if (!infoFile) {
                    addLog(`❌ Нет info.txt в папке ${name}`, '❌');
                    updateFolderStatus(name, 'error');
                    errors++;
                    processed++;
                    updateProgress(processed);
                    continue;
                }
                
                // Выбираем и сжимаем изображения
                const selected = imageFiles.slice(0, Math.min(maxPhotos, 10));
                addLog(`📸 Найдено ${selected.length} изображений`, '📸');
                
                const compressed = [];
                for (let i = 0; i < selected.length; i++) {
                    try {
                        addLog(`🔄 Сжатие ${i+1}/${selected.length}: ${selected[i].name}`, '🔄');
                        const img = await compressImage(selected[i], 1920, 1920, 0.85);
                        compressed.push(img);
                        totalImages++;
                    } catch(e) {
                        addLog(`⚠️ Ошибка сжатия ${selected[i].name}: ${e.message}`, '⚠️');
                    }
                }
                
                // Читаем текст объявления
                const infoText = await infoFile.text();
                const formData = new FormData();
                formData.append('user_id', userId);
                formData.append('max_photos', maxPhotos);
                formData.append('folders[]', JSON.stringify({
                    name: name,
                    adText: infoText.substring(0, 5000),
                    imageCount: compressed.length
                }));
                
                for (let i = 0; i < compressed.length; i++) {
                    formData.append('images_' + name + '_' + i, compressed[i], compressed[i].name);
                }
                
                // Отправка
                try {
                    addLog(`📤 Отправка ${idx+1}/${totalFolders}...`, '📤');
                    const resp = await fetch('/upload_folders', {
                        method: 'POST',
                        body: formData
                    });
                    
                    if (!resp.ok) {
                        const t = await resp.text();
                        throw new Error('HTTP ' + resp.status + ': ' + t.substring(0, 100));
                    }
                    
                    const result = await resp.json();
                    if (!result.success) {
                        throw new Error(result.message || 'Ошибка');
                    }
                    
                    updateFolderStatus(name, 'done');
                    successCount++;
                    addLog(`✅ Папка "${name}" успешно опубликована`, '✅');
                } catch(e) {
                    updateFolderStatus(name, 'error');
                    errors++;
                    addLog(`❌ Ошибка публикации "${name}": ${e.message}`, '❌');
                }
                
                processed++;
                updateProgress(processed);
                
                // Задержка между папками
                if (idx < folderQueue.length - 1) {
                    addLog(`⏳ Задержка ${delay} секунд...`, '⏳');
                    await new Promise(r => setTimeout(r, delay * 1000));
                }
            }
            
            // Завершение
            isProcessing = false;
            document.getElementById('uploadBtn').disabled = false;
            
            addLog(`✅ Загрузка завершена!`, '🎉');
            addLog(`📊 Успешно: ${successCount}, Ошибок: ${errors}, Фото: ${totalImages}`, '📊');
            
            if (errors === 0) {
                showStatus('success', `✅ Все ${totalFolders} папок успешно загружены!`);
            } else if (successCount > 0) {
                showStatus('warning', `⚠️ Загружено ${successCount} папок, ${errors} с ошибками`);
            } else {
                showStatus('error', `❌ Все ${totalFolders} папок завершились ошибкой`);
            }
            
            if (successCount > 0) {
                addLog(`📊 Скачать отчет: /report/${userId}`, '📊');
            }
            
            loadStats();
        }

        // Обновление прогресса
        function updateProgress(processed) {
            const pct = Math.round((processed / totalFolders) * 100);
            document.getElementById('progress').style.width = pct + '%';
            document.getElementById('progress').textContent = pct + '%';
            document.getElementById('progressText').textContent = 
                `Обработано ${processed} из ${totalFolders} папок (${pct}%)`;
        }
    </script>
</body>
</html>
'''

# ========== МАРШРУТЫ ==========

@app.route('/')
def index():
    return "🤖 MAX Bot is running!"

@app.route('/upload', methods=['GET'])
def upload_page():
    return render_template_string(UPLOAD_PAGE)

@app.route('/upload_folders', methods=['POST', 'OPTIONS'])
def upload_folders():
    """Обработка загрузки папок"""
    try:
        if request.method == 'OPTIONS':
            return '', 200
        
        # Проверяем инициализацию
        if publisher is None:
            if not init_app():
                return jsonify({'success': False, 'message': 'Ошибка инициализации'}), 500
        
        user_id = request.form.get('user_id', type=int)
        if not user_id:
            return jsonify({'success': False, 'message': 'Нет user_id'}), 400
        
        max_photos = request.form.get('max_photos', 6, type=int)
        max_photos = max(1, min(10, max_photos))
        
        folders_info = request.form.getlist('folders[]')
        if not folders_info:
            return jsonify({'success': False, 'message': 'Нет данных'}), 400
        
        folder_json = folders_info[0]
        folder_data = json.loads(folder_json)
        folder_name = folder_data.get('name', 'folder')
        ad_text = folder_data.get('adText', '')
        image_count = folder_data.get('imageCount', 0)
        
        MAX_IMAGE_SIZE = 5 * 1024 * 1024
        images = []
        
        # Собираем изображения из формы
        for i in range(min(image_count, max_photos)):
            field_name = f'images_{folder_name}_{i}'
            if field_name in request.files:
                img_file = request.files[field_name]
                try:
                    img_data = img_file.read()
                    
                    if len(img_data) > MAX_IMAGE_SIZE:
                        logger.warning(f"⚠️ {img_file.filename} слишком большой, пропускаем")
                        continue
                    
                    if img_data:
                        img_base64 = base64.b64encode(img_data).decode('ascii')
                        images.append({
                            'name': img_file.filename,
                            'data': img_base64,
                            'type': img_file.content_type or 'image/jpeg',
                            'bytes': img_data
                        })
                except Exception as e:
                    logger.error(f"❌ Ошибка чтения файла {img_file.filename}: {e}")
                    continue
                finally:
                    gc.collect()
        
        # Разбираем метаданные
        metadata_text = ''
        if '#изъятая' in ad_text:
            parts = ad_text.split('#изъятая')
            ad_text = parts[0].strip()
            metadata_text = parts[1] if len(parts) > 1 else ''
        
        # Публикуем папку
        success, message = publisher.publish_single_folder(
            user_id, folder_name, ad_text, metadata_text, images
        )
        
        # Очищаем память
        del images
        gc.collect()
        
        if success:
            return jsonify({
                'success': True,
                'message': message,
                'job_ids': ['sync'],
                'total_folders': 1,
                'total_images': len(images) if images else 0
            })
        else:
            return jsonify({'success': False, 'message': message}), 500
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        logger.info(f"📨 Получен вебхук: {data}")
        
        if not data:
            return jsonify({"ok": True}), 200
        
        user_id = None
        text = None
        
        if 'message' in data:
            msg = data['message']
            if 'sender' in msg:
                user_id = msg['sender'].get('user_id')
            elif 'user_id' in msg:
                user_id = msg['user_id']
            
            if 'body' in msg:
                if isinstance(msg['body'], dict):
                    text = msg['body'].get('text')
                else:
                    text = msg['body']
        
        if not user_id:
            if 'user' in data and 'user_id' in data['user']:
                user_id = data['user']['user_id']
        
        if not user_id:
            logger.warning("⚠️ Не найден user_id в вебхуке")
            return jsonify({"ok": True}), 200
        
        logger.info(f"👤 USER_ID: {user_id}, ТЕКСТ: {text}")
        
        if text and text.strip() == '/start':
            if db is None:
                init_app()
            
            stats = db.get_user_stats(user_id) if db else {'total': 0, 'success': 0, 'errors': 0}
            
            message_text = (
                f"🏠 **Главное меню**\n\n"
                f"📊 **Ваша статистика:**\n"
                f"📝 Всего публикаций: {stats['total']}\n"
                f"✅ Успешно: {stats['success']}\n"
                f"❌ Ошибок: {stats['errors']}\n\n"
                f"🌐 **Загрузить папку:**\n"
                f"🔗 {BASE_URL}/upload?user_id={user_id}\n\n"
                f"📊 **Получить отчет:**\n"
                f"🔗 {BASE_URL}/report/{user_id}"
            )
            
            url = f"{MAX_API_URL}/messages?user_id={user_id}"
            payload = {
                "text": message_text,
                "format": "markdown"
            }
            headers = {
                "Authorization": TOKEN,
                "Content-Type": "application/json"
            }
            
            response = requests.post(url, headers=headers, json=payload, timeout=30, verify=False)
            logger.info(f"✅ Ответ отправлен пользователю {user_id}, статус: {response.status_code}")
        
        return jsonify({"ok": True}), 200
        
    except Exception as e:
        logger.error(f"❌ Ошибка вебхука: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"ok": False}), 500

@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    try:
        if not BASE_URL:
            return jsonify({
                "success": False,
                "message": "BASE_URL не установлен в переменных окружения"
            }), 500
            
        webhook_url = f"{BASE_URL}/webhook"
        logger.info(f"🔄 Установка вебхука: {webhook_url}")
        
        url = f"{MAX_API_URL}/webhook"
        payload = {
            "url": webhook_url,
            "secret": app.secret_key
        }
        headers = {
            "Authorization": TOKEN,
            "Content-Type": "application/json"
        }
        
        response = requests.post(url, headers=headers, json=payload, timeout=30, verify=False)
        
        if response.status_code == 200:
            return jsonify({
                "success": True,
                "message": f"Вебхук установлен: {webhook_url}"
            })
        else:
            return jsonify({
                "success": False,
                "message": f"Ошибка: {response.status_code}",
                "response": response.text
            }), 500
            
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/report/<int:user_id>')
def report_page(user_id):
    if report_gen is None:
        init_app()
    
    report_path = report_gen.generate_report(user_id)
    if not report_path:
        return "❌ Нет данных", 404
    filename = os.path.basename(report_path)
    return f"""
    <html>
    <body style="text-align:center;padding:50px;font-family:Arial;">
        <h1>📊 Отчет готов!</h1>
        <p><a href="/download_report/{user_id}/{filename}">📥 Скачать</a></p>
        <p><a href="/upload">⬅️ Назад</a></p>
    </body>
    </html>
    """

@app.route('/download_report/<int:user_id>/<path:filename>')
def download_report(user_id, filename):
    try:
        if fm is None:
            init_app()
        
        user_folder = fm.get_user_folder(user_id)
        file_path = os.path.join(user_folder, filename)
        if not os.path.exists(file_path):
            return "❌ Файл не найден", 404
        return send_file(file_path, as_attachment=True, download_name=filename)
    except Exception as e:
        return str(e), 500

@app.route('/stats/<int:user_id>')
def get_stats(user_id):
    try:
        if db is None:
            init_app()
        
        stats = db.get_user_stats(user_id) if db else {'total': 0, 'success': 0, 'errors': 0}
        return jsonify(stats)
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        return jsonify({'total': 0, 'success': 0, 'errors': 0}), 500

@app.route('/health')
def health():
    return {"status": "ok", "database": "SQLite"}

@app.route('/status')
def status():
    return {
        "status": "running",
        "token_set": bool(TOKEN),
        "ssl_verify": False,
        "base_url": BASE_URL,
        "modules_initialized": db is not None
    }

# ========== ИНИЦИАЛИЗАЦИЯ ПРИ ЗАПУСКЕ ==========
init_app()

# ========== ЗАПУСК ==========
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
