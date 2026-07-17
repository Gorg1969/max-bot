# app.py - С ВСТРОЕННЫМ CORS (без flask-cors)

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
<html>
<head>
<meta charset="UTF-8">
<title>Загрузка объявлений</title>
<style>
body{font-family:Arial;max-width:900px;margin:50px auto;padding:20px;background:#f5f5f5}
.container{background:white;padding:30px;border-radius:10px;box-shadow:0 2px 10px rgba(0,0,0,0.1)}
h1{color:#333}
.drop-zone{border:2px dashed #007bff;padding:40px;margin:20px 0;border-radius:10px;background:#f8f9fa;text-align:center;cursor:pointer}
.drop-zone:hover{background:#e3f2fd}
.drop-zone.dragover{background:#d4edda;border-color:#28a745}
input[type=file]{display:none}
.btn{padding:12px 30px;border:none;border-radius:5px;cursor:pointer;font-size:16px;font-weight:bold}
.btn-success{background:#28a745;color:white}
.btn-success:hover{background:#218838}
.btn-danger{background:#dc3545;color:white}
.btn-danger:hover{background:#c82333}
.btn-warning{background:#ffc107;color:#333}
.btn-warning:hover{background:#e0a800}
.btn-info{background:#17a2b8;color:white}
.btn-info:hover{background:#138496}
.status{margin-top:20px;padding:15px;border-radius:5px;display:none}
.status.success{background:#d4edda;color:#155724;display:block;border-left:4px solid #28a745}
.status.error{background:#f8d7da;color:#721c24;display:block;border-left:4px solid #dc3545}
.status.info{background:#d1ecf1;color:#0c5460;display:block;border-left:4px solid #17a2b8}
.status.warning{background:#fff3cd;color:#856404;display:block;border-left:4px solid #ffc107}
.file-list{list-style:none;padding:0}
.file-list li{background:#f8f9fa;padding:10px 15px;margin:5px 0;border-radius:5px;border-left:3px solid #007bff;display:flex;justify-content:space-between;align-items:center}
.file-list li .count{background:#007bff;color:white;padding:2px 10px;border-radius:20px;font-size:12px}
.file-list li .status-badge{font-size:12px;padding:2px 10px;border-radius:20px;margin-left:10px}
.file-list li .status-badge.pending{background:#ffc107;color:#333}
.file-list li .status-badge.done{background:#28a745;color:white}
.file-list li .status-badge.error{background:#dc3545;color:white}
.progress-bar{width:100%;height:25px;background:#e9ecef;border-radius:10px;overflow:hidden;margin:10px 0;display:none}
.progress-bar .progress{height:100%;background:linear-gradient(90deg,#28a745,#20c997);transition:width .3s;width:0%;display:flex;align-items:center;justify-content:center;color:white;font-size:12px;font-weight:bold}
.instructions{background:#fff3cd;padding:15px;border-radius:5px;margin:20px 0;border-left:4px solid #ffc107}
.settings-section{background:#e7f5ff;padding:15px;border-radius:10px;margin:15px 0}
.settings-section label{display:inline-block;margin-right:15px;font-weight:bold}
.settings-section input[type=number]{width:60px;padding:5px;border:1px solid #ccc;border-radius:5px}
#log{background:#1e1e1e;color:#d4d4d4;padding:15px;border-radius:5px;font-family:monospace;font-size:12px;max-height:300px;overflow-y:auto;margin:20px 0;display:none;white-space:pre-wrap}
.button-group{display:flex;gap:10px;flex-wrap:wrap;margin-top:15px}
.selected-info{background:#e7f5ff;padding:10px 15px;border-radius:5px;margin:10px 0;border-left:3px solid #007bff}
.queue-info{background:#f8f9fa;padding:10px 15px;border-radius:5px;margin:10px 0;border-left:3px solid #17a2b8}
.footer{text-align:center;margin-top:30px;color:#999;font-size:14px}
.report-section{margin-top:20px;padding:20px;background:#f8f9fa;border-radius:10px;border:1px solid #dee2e6;text-align:center}
.stats-section{display:grid;grid-template-columns:repeat(3,1fr);gap:15px;margin:20px 0}
.stat-card{background:white;padding:20px;border-radius:10px;box-shadow:0 2px 5px rgba(0,0,0,0.1);text-align:center}
.stat-card .number{font-size:32px;font-weight:bold;color:#007bff}
.stat-card .label{color:#666;font-size:14px;margin-top:5px}
</style>
</head>
<body>
<div class="container">
<h1>📤 Загрузка объявлений</h1>
<div class="instructions">
<strong>📌 Как подготовить:</strong><br>
1️⃣ Создайте головную папку с подпапками<br>
2️⃣ В каждой подпапке: info.txt и фото (макс 10)<br>
3️⃣ Используйте разделитель #изъятая<br>
4️⃣ Перетащите головную папку в поле ниже<br>
5️⃣ Папки отправляются по одной с задержкой
</div>
<div class="settings-section">
<h4>⚙️ Настройки</h4>
<label>📸 Максимум фото: <input type="number" id="maxPhotos" value="6" min="1" max="10"></label>
<label>⏱️ Задержка между папками (сек): <input type="number" id="delayBetween" value="3" min="1" max="30"></label>
</div>
<div class="drop-zone" id="dropZone">
<span style="font-size:48px;">📂</span>
<p><strong>Перетащите головную папку сюда</strong></p>
<button class="btn btn-success" onclick="document.getElementById('folderInput').click()">Выбрать папку</button>
<input type="file" id="folderInput" webkitdirectory multiple>
</div>
<div id="fileList" style="display:none;">
<div class="selected-info" id="selectedInfo"></div>
<div class="queue-info"><strong>📋 Очередь:</strong> <span id="queueStatus">Ожидание</span></div>
<ul class="file-list" id="fileListContent"></ul>
<div class="button-group">
<button class="btn btn-success" onclick="uploadFolder()">🚀 Загрузить</button>
<button class="btn btn-danger" onclick="clearFiles()">🗑️ Очистить</button>
</div>
</div>
<div class="progress-bar" id="progressBar"><div class="progress" id="progress">0%</div></div>
<div id="status" class="status"></div>
<div id="log"></div>
<div class="stats-section" id="statsSection">
<div class="stat-card"><div class="number" id="statTotal">0</div><div class="label">Всего публикаций</div></div>
<div class="stat-card" style="border-top:3px solid #28a745;"><div class="number" id="statSuccess" style="color:#28a745;">0</div><div class="label">✅ Успешно</div></div>
<div class="stat-card" style="border-top:3px solid #dc3545;"><div class="number" id="statErrors" style="color:#dc3545;">0</div><div class="label">❌ Ошибок</div></div>
</div>
<div class="report-section">
<button class="btn btn-success" onclick="getReport()">📊 Скачать отчет</button>
<button class="btn btn-info" onclick="loadStats()">🔄 Обновить статистику</button>
<p style="margin-top:10px;color:#666;font-size:14px;">После публикации всех папок</p>
</div>
<div class="footer">⚡ MAX Bot | SQLite</div>
</div>

<script>
const userId = new URLSearchParams(window.location.search).get('user_id') || 151296248;
let selectedFiles = [], isProcessing = false, folderQueue = [], totalFolders = 0;

window.onload = function() { loadStats(); };

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
                            readDirectoryRecursive(e, path + e.name + '/', files, () => { pending--; if (pending === 0) callback(); });
                        } else {
                            e.file((file) => { file.webkitRelativePath = path + file.name; files.push(file); pending--; if (pending === 0) callback(); });
                        }
                    });
                } else { allEntries = allEntries.concat(entries); readEntries(); }
            });
        }
        readEntries();
    } else {
        entry.file((file) => { file.webkitRelativePath = path + file.name; files.push(file); callback(); });
    }
}

const dropZone = document.getElementById('dropZone');
const folderInput = document.getElementById('folderInput');

dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('dragover'); });
dropZone.addEventListener('dragleave', () => { dropZone.classList.remove('dragover'); });
dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    const items = e.dataTransfer.items;
    const files = [];
    let pending = 0;
    for (let item of items) {
        if (item.kind === 'file') {
            const entry = item.webkitGetAsEntry();
            if (entry) { pending++; readDirectoryRecursive(entry, '', files, () => { pending--; if (pending === 0) { selectedFiles = files; displayFiles(selectedFiles); } }); }
        }
    }
    if (pending === 0 && files.length > 0) { selectedFiles = files; displayFiles(selectedFiles); }
});

folderInput.addEventListener('change', (e) => {
    const files = Array.from(e.target.files);
    if (files.length > 0) { selectedFiles = files; displayFiles(selectedFiles); }
});

function compressImage(file, maxWidth = 1920, maxHeight = 1920, quality = 0.85) {
    return new Promise((resolve, reject) => {
        if (file.size > 20 * 1024 * 1024) { reject(new Error('Файл слишком большой')); return; }
        const reader = new FileReader();
        reader.onload = function(e) {
            const img = new Image();
            img.onload = function() {
                let w = img.width, h = img.height;
                if (w > maxWidth) { h = (h * maxWidth) / w; w = maxWidth; }
                if (h > maxHeight) { w = (w * maxHeight) / h; h = maxHeight; }
                const canvas = document.createElement('canvas');
                canvas.width = w; canvas.height = h;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0, w, h);
                canvas.toBlob((blob) => {
                    if (blob) { resolve(new File([blob], file.name, { type: 'image/jpeg', lastModified: Date.now() })); }
                    else { reject(new Error('Не удалось сжать')); }
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
    const container = document.getElementById('fileListContent');
    container.innerHTML = '';
    const folders = new Map();
    files.forEach(f => {
        const parts = f.webkitRelativePath.split('/');
        if (parts.length >= 2) {
            const root = parts[0];
            const sub = parts.length > 2 ? parts.slice(1, -1).join('/') : 'root';
            const key = root + '/' + sub;
            if (!folders.has(key)) { folders.set(key, { root: root, sub: sub, display: sub === 'root' ? root : root + '/' + sub, count: 0, files: [] }); }
            folders.get(key).count++;
            folders.get(key).files.push(f);
        }
    });
    const sorted = Array.from(folders.values()).sort((a, b) => a.display.localeCompare(b.display));
    folderQueue = sorted.map(f => ({ name: f.display, status: 'pending', count: f.count, files: f.files }));
    sorted.forEach(folder => {
        const li = document.createElement('li');
        const isSub = folder.sub !== 'root';
        li.innerHTML = `<span>${isSub ? '📂' : '📁'} <strong>${folder.display}</strong></span><span><span class="count">${folder.count} файлов</span><span class="status-badge pending" id="st-${folder.display.replace(/\\//g,'-')}">⏳</span></span>`;
        li.style.borderLeftColor = isSub ? '#28a745' : '#007bff';
        container.appendChild(li);
    });
    document.getElementById('selectedInfo').textContent = `✅ Найдено ${sorted.length} папок, ${files.length} файлов`;
    document.getElementById('fileList').style.display = 'block';
    updateQueueStatus();
    totalFolders = sorted.length;
}

function updateQueueStatus() {
    const done = folderQueue.filter(f => f.status === 'done').length;
    const errors = folderQueue.filter(f => f.status === 'error').length;
    const total = folderQueue.length;
    document.getElementById('queueStatus').textContent = isProcessing ? `🔄 ${done+errors}/${total}` : `📋 ${done}/${total}`;
    if (errors > 0) document.getElementById('queueStatus').textContent += ` ⚠️${errors}`;
}

function updateFolderStatus(name, status) {
    const idx = folderQueue.findIndex(f => f.name === name);
    if (idx !== -1) {
        folderQueue[idx].status = status;
        updateQueueStatus();
        const badge = document.getElementById('st-' + name.replace(/\\//g,'-'));
        if (badge) {
            badge.className = 'status-badge ' + status;
            badge.textContent = status === 'pending' ? '⏳' : status === 'processing' ? '🔄' : status === 'done' ? '✅' : '❌';
        }
    }
}

function addLog(msg) {
    const log = document.getElementById('log');
    log.style.display = 'block';
    log.textContent += msg + '\\n';
    log.scrollTop = log.scrollHeight;
}

function showStatus(type, msg) {
    const s = document.getElementById('status');
    s.className = 'status ' + type;
    s.textContent = msg;
    s.style.display = 'block';
}

function getReport() { window.open('/report/' + userId, '_blank'); }

function clearFiles() {
    if (isProcessing && !confirm('Остановить?')) return;
    selectedFiles = []; folderQueue = [];
    document.getElementById('fileList').style.display = 'none';
    document.getElementById('status').style.display = 'none';
    document.getElementById('progressBar').style.display = 'none';
    document.getElementById('log').style.display = 'none';
    document.getElementById('progress').style.width = '0%';
    document.getElementById('progress').textContent = '0%';
    folderInput.value = '';
    isProcessing = false;
}

async function uploadFolder() {
    if (selectedFiles.length === 0) { showStatus('error', '❌ Выберите папку'); return; }
    if (isProcessing) { addLog('⚠️ Уже выполняется'); return; }
    
    isProcessing = true;
    const maxPhotos = parseInt(document.getElementById('maxPhotos').value) || 6;
    const delay = parseInt(document.getElementById('delayBetween').value) || 3;
    
    document.getElementById('progressBar').style.display = 'block';
    document.getElementById('progress').style.width = '0%';
    document.getElementById('progress').textContent = '0%';
    document.getElementById('log').textContent = '';
    addLog('🚀 Загрузка ' + totalFolders + ' папок по одной...');
    
    let processed = 0, totalImages = 0, errors = 0;
    
    for (let idx = 0; idx < folderQueue.length; idx++) {
        const folder = folderQueue[idx];
        const name = folder.name;
        const files = folder.files;
        
        updateFolderStatus(name, 'processing');
        addLog('📂 [' + (idx+1) + '/' + totalFolders + '] ' + name);
        
        let infoFile = null, imageFiles = [];
        for (const f of files) {
            const fn = f.name.toLowerCase();
            if (fn.endsWith('.txt') && fn.includes('info')) infoFile = f;
            else if (fn.match(/\\.(jpg|jpeg|png|gif|bmp|webp)$/)) {
                if (f.size > 5 * 1024 * 1024) { addLog('⚠️ ' + f.name + ' слишком большой, пропускаем'); continue; }
                imageFiles.push(f);
            }
        }
        
        if (!infoFile) { addLog('⚠️ Нет info.txt в ' + name); updateFolderStatus(name, 'error'); errors++; processed++; updateProgress(processed); continue; }
        
        const selected = imageFiles.slice(0, Math.min(maxPhotos, 10));
        addLog('📸 ' + selected.length + ' фото');
        
        const compressed = [];
        for (let i = 0; i < selected.length; i++) {
            try {
                addLog('🔄 Сжатие ' + (i+1) + '/' + selected.length + ': ' + selected[i].name);
                const img = await compressImage(selected[i], 1920, 1920, 0.85);
                compressed.push(img);
                totalImages++;
            } catch(e) { addLog('⚠️ Ошибка сжатия: ' + e.message); }
        }
        
        const infoText = await infoFile.text();
        const formData = new FormData();
        formData.append('user_id', userId);
        formData.append('max_photos', maxPhotos);
        formData.append('folders[]', JSON.stringify({ name: name, adText: infoText.substring(0,5000), imageCount: compressed.length }));
        for (let i = 0; i < compressed.length; i++) {
            formData.append('images_' + name + '_' + i, compressed[i], compressed[i].name);
        }
        
        try {
            addLog('📤 Отправка ' + (idx+1) + '/' + totalFolders + '...');
            const resp = await fetch('/upload_folders', { method: 'POST', body: formData });
            if (!resp.ok) { const t = await resp.text(); throw new Error('HTTP ' + resp.status + ': ' + t.substring(0,100)); }
            const result = await resp.json();
            if (!result.success) throw new Error(result.message || 'Ошибка');
            updateFolderStatus(name, 'done');
            addLog('✅ Папка ' + name + ' опубликована');
        } catch(e) {
            updateFolderStatus(name, 'error');
            errors++;
            addLog('❌ ' + e.message);
        }
        
        processed++;
        updateProgress(processed);
        
        if (idx < folderQueue.length - 1) {
            addLog('⏳ Задержка ' + delay + ' сек...');
            await new Promise(r => setTimeout(r, delay * 1000));
        }
    }
    
    isProcessing = false;
    addLog('✅ Готово! ' + (totalFolders - errors) + ' папок загружено, ' + errors + ' с ошибками');
    addLog('📊 Всего фото: ' + totalImages);
    if (errors === 0) { showStatus('success', '✅ Загружено ' + totalFolders + ' папок!'); }
    else { showStatus('warning', '⚠️ Загружено ' + (totalFolders - errors) + ' папок, ' + errors + ' с ошибками'); }
    if (totalFolders - errors > 0) { addLog('📊 Скачать отчет: /report/' + userId); }
    
    loadStats();
}

function updateProgress(processed) {
    const pct = Math.round((processed / totalFolders) * 100);
    document.getElementById('progress').style.width = pct + '%';
    document.getElementById('progress').textContent = pct + '%';
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
                    # Читаем файл
                    img_data = img_file.read()
                    
                    if len(img_data) > MAX_IMAGE_SIZE:
                        logger.warning(f"⚠️ {img_file.filename} слишком большой, пропускаем")
                        continue
                    
                    if img_data:
                        # Формируем данные для publisher
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
                    # Освобождаем память
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
            # Проверяем инициализацию БД
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
# Инициализируем модули при старте
init_app()

# ========== ЗАПУСК ==========
if __name__ == '__main__':
    # Для локального запуска
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
