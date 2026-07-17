from flask import Flask, request, jsonify, render_template_string, send_file
import requests
import logging
import os
import json
import re
import time
import sqlite3
from datetime import datetime
import urllib3
import threading
import base64

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
app.secret_key = "SUPER_SECRET_KEY_CHANGE_ME"
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== НАСТРОЙКИ ==========
TOKEN = os.environ.get("MAX_TOKEN", "ВАШ_ТОКЕН_ЗДЕСЬ")
MAX_API_URL = "https://platform-api2.max.ru"
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

# ========== БАЗА ДАННЫХ ==========
class Database:
    def __init__(self):
        self.db_path = os.path.join(DATA_DIR, "bot.db")
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS ads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            folder_name TEXT,
            chat_id TEXT,
            title TEXT,
            link TEXT,
            code TEXT,
            price TEXT,
            published_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS tokens (
            user_id INTEGER PRIMARY KEY,
            token TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        conn.commit()
        conn.close()
    
    def add_user(self, user_id, username=None):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)', (user_id, username))
        conn.commit()
        conn.close()
    
    def save_ad(self, user_id, folder_name, chat_id, title, link, code, price):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''INSERT INTO ads (user_id, folder_name, chat_id, title, link, code, price, published_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', 
            (user_id, folder_name, chat_id, title, link, code, price, datetime.now()))
        conn.commit()
        conn.close()
    
    def get_ads(self, user_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''SELECT folder_name, chat_id, title, link, code, price, published_at 
            FROM ads WHERE user_id = ? ORDER BY published_at DESC''', (user_id,))
        rows = c.fetchall()
        conn.close()
        return rows
    
    def save_token(self, user_id, token):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO tokens (user_id, token) VALUES (?, ?)', (user_id, token))
        conn.commit()
        conn.close()
    
    def get_token(self, user_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT token FROM tokens WHERE user_id = ?', (user_id,))
        row = c.fetchone()
        conn.close()
        return row[0] if row else None

db = Database()

# ========== PUBLISHER ==========
class Publisher:
    def __init__(self, token):
        self.token = token
        self.base_url = MAX_API_URL
        self.stop_flags = {}
    
    def extract_chat_id(self, folder_name):
        match = re.search(r'-\s*(\d+)', folder_name)
        if match:
            chat_id = match.group(1)
            if len(chat_id) >= 10:
                return chat_id
        match = re.search(r'(\d{10,})$', folder_name)
        if match:
            return match.group(1)
        return None
    
    def upload_image(self, image_data):
        try:
            # Получаем URL для загрузки
            resp = requests.post(
                f"{self.base_url}/uploads",
                headers={"Authorization": self.token},
                params={"type": "image"},
                timeout=30,
                verify=False
            )
            if resp.status_code != 200:
                return None
            upload_url = resp.json().get('url')
            if not upload_url:
                return None
            
            # Загружаем изображение
            files = {'data': ('image.jpg', image_data, 'image/jpeg')}
            resp = requests.post(upload_url, files=files, timeout=60, verify=False)
            if resp.status_code != 200:
                return None
            
            result = resp.json()
            token = None
            if 'photos' in result:
                for photo in result['photos'].values():
                    if isinstance(photo, dict) and 'token' in photo:
                        token = photo['token']
                        break
            if not token and 'token' in result:
                token = result['token']
            return token
        except Exception as e:
            logger.error(f"Ошибка загрузки: {e}")
            return None
    
    def send_to_chat(self, chat_id, text, image_tokens):
        try:
            attachments = []
            for token in image_tokens[:10]:
                attachments.append({"type": "image", "payload": {"token": token}})
            
            payload = {"text": text, "format": "markdown"}
            if attachments:
                payload["attachments"] = attachments
            
            chat_id_with_dash = f"-{chat_id}" if not str(chat_id).startswith('-') else chat_id
            
            resp = requests.post(
                f"{self.base_url}/messages?chat_id={chat_id_with_dash}",
                headers={"Authorization": self.token, "Content-Type": "application/json"},
                json=payload,
                timeout=60,
                verify=False
            )
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"Ошибка отправки: {e}")
            return False
    
    def publish(self, user_id, folder_name, ad_text, metadata, images):
        try:
            chat_id = self.extract_chat_id(folder_name)
            if not chat_id:
                return False, "Не удалось извлечь chat_id"
            
            # Загружаем изображения
            image_tokens = []
            for img in images[:10]:
                token = self.upload_image(img)
                if token:
                    image_tokens.append(token)
            
            # Отправляем в чат
            success = self.send_to_chat(chat_id, ad_text, image_tokens)
            if not success:
                return False, "Не удалось отправить в чат"
            
            # Сохраняем в БД
            db.save_ad(
                user_id, folder_name, f"-{chat_id}",
                metadata.get('Название', ''),
                metadata.get('Ссылка', ''),
                metadata.get('Код предложения', ''),
                metadata.get('Цена в лизинге', '')
            )
            
            return True, f"Опубликовано с {len(image_tokens)} фото"
        except Exception as e:
            return False, str(e)

publisher = Publisher(TOKEN)

# ========== HTML СТРАНИЦА (КРАСИВЫЙ ИНТЕРФЕЙС) ==========
UPLOAD_PAGE = '''
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MAX Bot - Загрузка</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Arial, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; padding: 20px; }
        .container { max-width: 900px; margin: 0 auto; background: white; border-radius: 20px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); padding: 40px; }
        h1 { text-align: center; color: #333; margin-bottom: 10px; }
        .subtitle { text-align: center; color: #888; margin-bottom: 30px; }
        .drop-zone { border: 3px dashed #667eea; padding: 60px 20px; border-radius: 16px; text-align: center; cursor: pointer; transition: 0.3s; background: #f8f9ff; }
        .drop-zone:hover { background: #f0f2ff; border-color: #764ba2; }
        .drop-zone.dragover { background: #e8f5e9; border-color: #4caf50; transform: scale(1.02); }
        .drop-zone .icon { font-size: 64px; margin-bottom: 15px; }
        .drop-zone p { color: #666; font-size: 18px; }
        .btn { padding: 12px 30px; border: none; border-radius: 10px; cursor: pointer; font-size: 16px; font-weight: 600; transition: 0.3s; }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 5px 20px rgba(0,0,0,0.15); }
        .btn-primary { background: linear-gradient(135deg, #667eea, #764ba2); color: white; }
        .btn-success { background: linear-gradient(135deg, #43a047, #66bb6a); color: white; }
        .btn-danger { background: linear-gradient(135deg, #e53935, #ef5350); color: white; }
        .btn-info { background: linear-gradient(135deg, #00838f, #26c6da); color: white; }
        .file-list-section { display: none; margin: 20px 0; }
        .file-list-section.visible { display: block; }
        .selected-info { background: #e3f2fd; padding: 12px 20px; border-radius: 10px; margin: 10px 0; border-left: 4px solid #2196f3; }
        .file-list { list-style: none; padding: 0; max-height: 400px; overflow-y: auto; }
        .file-list li { background: #f8f9fa; padding: 12px 18px; margin: 6px 0; border-radius: 10px; border-left: 4px solid #667eea; display: flex; justify-content: space-between; align-items: center; }
        .file-list li .count { background: #667eea; color: white; padding: 2px 12px; border-radius: 20px; font-size: 12px; }
        .button-group { display: flex; gap: 10px; flex-wrap: wrap; margin: 15px 0; }
        .progress-section { display: none; margin: 20px 0; }
        .progress-section.visible { display: block; }
        .progress-bar { width: 100%; height: 30px; background: #e9ecef; border-radius: 15px; overflow: hidden; }
        .progress-bar .progress { height: 100%; background: linear-gradient(90deg, #667eea, #764ba2); transition: width 0.5s; display: flex; align-items: center; justify-content: center; color: white; font-size: 13px; font-weight: 600; width: 0%; }
        .status { padding: 15px 20px; border-radius: 12px; display: none; font-weight: 500; margin: 20px 0; }
        .status.visible { display: block; }
        .status.success { background: #e8f5e9; color: #1b5e20; border-left: 4px solid #4caf50; }
        .status.error { background: #ffebee; color: #b71c1c; border-left: 4px solid #f44336; }
        .status.warning { background: #fff3e0; color: #e65100; border-left: 4px solid #ff9800; }
        #log { background: #1a1a2e; color: #e0e0e0; padding: 20px; border-radius: 12px; font-family: monospace; font-size: 13px; max-height: 350px; overflow-y: auto; white-space: pre-wrap; line-height: 1.6; display: none; }
        #log .time { color: #888; margin-right: 10px; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin: 20px 0; }
        .stat-card { background: #f8f9fa; padding: 20px; border-radius: 12px; text-align: center; border: 1px solid #e9ecef; }
        .stat-card .number { font-size: 32px; font-weight: 700; color: #333; }
        .stat-card .label { color: #888; font-size: 14px; margin-top: 5px; }
        .report-section { background: #f8f9fa; padding: 25px; border-radius: 12px; text-align: center; margin: 20px 0; }
        .footer { text-align: center; margin-top: 30px; padding-top: 20px; border-top: 2px solid #f0f0f0; color: #999; }
        @media(max-width:768px){ .container { padding: 20px; } }
        input[type="file"] { display: none; }
    </style>
</head>
<body>
<div class="container">
    <h1>📤 Загрузка объявлений</h1>
    <p class="subtitle">Перетащите папку с объявлениями для публикации в MAX</p>
    
    <div class="drop-zone" id="dropZone">
        <div class="icon">📂</div>
        <p><strong>Перетащите головную папку сюда</strong></p>
        <br>
        <button class="btn btn-primary" onclick="document.getElementById('folderInput').click()">📁 Выбрать папку</button>
        <input type="file" id="folderInput" webkitdirectory multiple>
    </div>
    
    <div class="file-list-section" id="fileListSection">
        <div class="selected-info" id="selectedInfo"></div>
        <ul class="file-list" id="fileListContent"></ul>
        <div class="button-group">
            <button class="btn btn-success" onclick="uploadFolder()" id="uploadBtn">🚀 Начать загрузку</button>
            <button class="btn btn-danger" onclick="clearFiles()">🗑️ Очистить</button>
        </div>
    </div>
    
    <div class="progress-section" id="progressSection">
        <div class="progress-bar"><div class="progress" id="progress">0%</div></div>
    </div>
    
    <div class="status" id="status"></div>
    
    <div id="log"></div>
    
    <div class="stats-grid" id="statsGrid">
        <div class="stat-card total"><div class="number" id="statTotal">0</div><div class="label">📊 Всего</div></div>
        <div class="stat-card success"><div class="number" id="statSuccess">0</div><div class="label">✅ Успешно</div></div>
        <div class="stat-card error"><div class="number" id="statErrors">0</div><div class="label">❌ Ошибок</div></div>
    </div>
    
    <div class="report-section">
        <button class="btn btn-info" onclick="getReport()">📊 Скачать отчет</button>
    </div>
    
    <div class="footer">⚡ MAX Bot</div>
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
        .catch(err => console.error(err));
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
        li.innerHTML = `<span>📁 <strong>${folder.display}</strong></span><span class="count">${folder.count} файлов</span>`;
        container.appendChild(li);
    });
    document.getElementById('selectedInfo').textContent = `✅ Найдено ${sorted.length} папок, ${files.length} файлов`;
    document.getElementById('fileListSection').classList.add('visible');
    totalFolders = sorted.length;
    document.getElementById('uploadBtn').disabled = false;
}

function addLog(msg) {
    const log = document.getElementById('log');
    log.style.display = 'block';
    const time = new Date().toLocaleTimeString();
    log.innerHTML += `<div><span class="time">[${time}]</span>${msg}</div>`;
    log.scrollTop = log.scrollHeight;
}

function showStatus(type, msg) {
    const s = document.getElementById('status');
    s.className = 'status ' + type + ' visible';
    s.textContent = msg;
}

function getReport() { window.open('/report/' + userId, '_blank'); }

function clearFiles() {
    if (isProcessing && !confirm('Остановить?')) return;
    selectedFiles = []; folderQueue = [];
    document.getElementById('fileListSection').classList.remove('visible');
    document.getElementById('status').className = 'status';
    document.getElementById('progressSection').classList.remove('visible');
    document.getElementById('progress').style.width = '0%';
    document.getElementById('log').innerHTML = '';
    folderInput.value = '';
    isProcessing = false;
    document.getElementById('uploadBtn').disabled = false;
}

async function uploadFolder() {
    if (selectedFiles.length === 0) { showStatus('error', '❌ Выберите папку'); return; }
    if (isProcessing) { addLog('⚠️ Уже выполняется'); return; }
    
    isProcessing = true;
    document.getElementById('uploadBtn').disabled = true;
    document.getElementById('progressSection').classList.add('visible');
    document.getElementById('progress').style.width = '0%';
    document.getElementById('log').innerHTML = '';
    
    addLog('🚀 Загрузка ' + totalFolders + ' папок');
    let processed = 0, errors = 0, successCount = 0;
    
    for (let idx = 0; idx < folderQueue.length; idx++) {
        const folder = folderQueue[idx];
        const name = folder.name;
        const files = folder.files;
        
        addLog('📂 [' + (idx+1) + '/' + totalFolders + '] ' + name);
        
        let infoFile = null, imageFiles = [];
        for (const f of files) {
            const fn = f.name.toLowerCase();
            if (fn.endsWith('.txt') && fn.includes('info')) infoFile = f;
            else if (fn.match(/\\.(jpg|jpeg|png|gif|bmp|webp)$/)) {
                if (f.size > 5 * 1024 * 1024) { addLog('⚠️ ' + f.name + ' слишком большой'); continue; }
                imageFiles.push(f);
            }
        }
        
        if (!infoFile) { addLog('❌ Нет info.txt в ' + name); errors++; processed++; updateProgress(processed); continue; }
        
        const infoText = await infoFile.text();
        let adText = infoText;
        let metadataText = '';
        if (infoText.includes('#изъятая')) {
            const parts = infoText.split('#изъятая');
            adText = parts[0].trim();
            metadataText = parts[1] ? parts[1].trim() : '';
        }
        
        // Читаем изображения
        const images = [];
        for (const img of imageFiles.slice(0, 6)) {
            try {
                const arrayBuffer = await img.arrayBuffer();
                images.push(new Uint8Array(arrayBuffer));
            } catch(e) { addLog('⚠️ Ошибка чтения ' + img.name); }
        }
        
        addLog('📸 ' + images.length + ' фото');
        
        try {
            const formData = new FormData();
            formData.append('user_id', userId);
            formData.append('folder_name', name);
            formData.append('ad_text', adText);
            formData.append('metadata_text', metadataText);
            for (const img of images) {
                const blob = new Blob([img], { type: 'image/jpeg' });
                formData.append('images[]', blob, 'image.jpg');
            }
            
            const resp = await fetch('/publish', { method: 'POST', body: formData });
            const result = await resp.json();
            
            if (result.success) {
                successCount++;
                addLog('✅ ' + name + ' опубликована');
            } else {
                errors++;
                addLog('❌ ' + name + ': ' + result.message);
            }
        } catch(e) {
            errors++;
            addLog('❌ ' + name + ': ' + e.message);
        }
        
        processed++;
        updateProgress(processed);
        await new Promise(r => setTimeout(r, 2000));
    }
    
    isProcessing = false;
    document.getElementById('uploadBtn').disabled = false;
    addLog('✅ Готово! Успешно: ' + successCount + ', Ошибок: ' + errors);
    if (errors === 0) { showStatus('success', '✅ Загружено ' + totalFolders + ' папок!'); }
    else { showStatus('warning', '⚠️ Загружено ' + successCount + ' папок, ' + errors + ' с ошибками'); }
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
    return render_template_string('''
    <html><body style="font-family:Arial;text-align:center;padding:50px;">
        <h1>🤖 MAX Bot</h1>
        <p>Перейдите на <a href="/upload">/upload</a> для загрузки</p>
    </body></html>
    ''')

@app.route('/upload', methods=['GET'])
def upload_page():
    return render_template_string(UPLOAD_PAGE)

@app.route('/publish', methods=['POST'])
def publish():
    try:
        user_id = int(request.form.get('user_id', 0))
        folder_name = request.form.get('folder_name')
        ad_text = request.form.get('ad_text')
        metadata_text = request.form.get('metadata_text')
        
        if not user_id or not folder_name or not ad_text:
            return jsonify({'success': False, 'message': 'Нет данных'})
        
        # Парсим метаданные
        metadata = {}
        if metadata_text:
            fields = {
                'Название': r'Название:\s*(.+)',
                'Ссылка': r'Ссылка:\s*(.+)',
                'Код предложения': r'Код предложения:\s*(.+)',
                'Цена в лизинге': r'Цена\s*[вВ]\s*лизинге:\s*(.+)',
            }
            for key, pattern in fields.items():
                match = re.search(pattern, metadata_text, re.IGNORECASE)
                if match:
                    metadata[key] = match.group(1).strip()
        
        # Читаем изображения
        images = []
        for file in request.files.getlist('images[]'):
            if file and file.filename:
                images.append(file.read())
        
        # Публикуем
        success, message = publisher.publish(user_id, folder_name, ad_text, metadata, images)
        return jsonify({'success': success, 'message': message})
        
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/stats/<int:user_id>')
def stats(user_id):
    ads = db.get_ads(user_id)
    return jsonify({
        'total': len(ads),
        'success': len([a for a in ads if a[0]]),
        'errors': 0
    })

@app.route('/report/<int:user_id>')
def report(user_id):
    ads = db.get_ads(user_id)
    if not ads:
        return "❌ Нет данных для отчета", 404
    
    # Генерируем HTML отчет
    html = '''
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Отчет</title>
        <style>
            body { font-family: Arial; padding: 30px; background: #f5f5f5; }
            .container { max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            h1 { color: #333; }
            table { width: 100%; border-collapse: collapse; margin: 20px 0; }
            th { background: #667eea; color: white; padding: 12px; text-align: left; }
            td { padding: 10px 12px; border-bottom: 1px solid #eee; }
            tr:hover { background: #f8f9ff; }
            .btn { display: inline-block; padding: 10px 25px; background: #667eea; color: white; text-decoration: none; border-radius: 5px; margin: 10px 0; }
            .btn:hover { background: #5a6fd6; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📊 Отчет по публикациям</h1>
            <p>Пользователь: <strong>''' + str(user_id) + '''</strong></p>
            <p>Всего публикаций: <strong>''' + str(len(ads)) + '''</strong></p>
            <a href="/download_report/''' + str(user_id) + '''" class="btn">📥 Скачать CSV</a>
            <a href="/upload" class="btn" style="background:#6c757d;">⬅️ Назад</a>
            <table>
                <tr><th>#</th><th>Папка</th><th>Название</th><th>Ссылка</th><th>Код</th><th>Цена</th><th>Дата</th></tr>
    '''
    
    for i, ad in enumerate(ads, 1):
        html += f'''
            <tr>
                <td>{i}</td>
                <td>{ad[0]}</td>
                <td>{ad[2] or ''}</td>
                <td><a href="{ad[3]}" target="_blank">{ad[3][:30] if ad[3] else ''}</a></td>
                <td>{ad[4] or ''}</td>
                <td>{ad[5] or ''}</td>
                <td>{ad[6]}</td>
            </tr>
        '''
    
    html += '''
            </table>
        </div>
    </body>
    </html>
    '''
    return html

@app.route('/download_report/<int:user_id>')
def download_report(user_id):
    ads = db.get_ads(user_id)
    if not ads:
        return "Нет данных", 404
    
    import csv
    from io import StringIO
    
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Папка', 'Название', 'Ссылка', 'Код', 'Цена', 'Дата'])
    for ad in ads:
        writer.writerow([ad[0], ad[2] or '', ad[3] or '', ad[4] or '', ad[5] or '', ad[6]])
    
    response = app.response_class(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment;filename=report_{user_id}.csv'}
    )
    return response

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
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
        
        if text and text.strip() == '/start':
            db.add_user(user_id)
            upload_url = f"{MAX_API_URL}/upload?user_id={user_id}"  # ВАШ URL
            
            msg = f"""🏠 **Главное меню**
            
📊 **Ваша статистика:**
📝 Всего: 0
✅ Успешно: 0

🌐 **Загрузить папку:**
🔗 {upload_url}

📊 **Отчет:**
🔗 {MAX_API_URL}/report/{user_id}"""
            
            requests.post(
                f"{MAX_API_URL}/messages?user_id={user_id}",
                headers={"Authorization": TOKEN, "Content-Type": "application/json"},
                json={"text": msg, "format": "markdown"},
                timeout=30,
                verify=False
            )
        
        return jsonify({"ok": True}), 200
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        return jsonify({"ok": False}), 500

@app.route('/setup_webhook')
def setup_webhook():
    webhook_url = request.host_url.rstrip('/') + '/webhook'
    resp = requests.post(
        f"{MAX_API_URL}/subscriptions",
        headers={"Authorization": TOKEN, "Content-Type": "application/json"},
        json={"url": webhook_url, "update_types": ["message_created"]},
        timeout=10,
        verify=False
    )
    return f"✅ Вебхук: {webhook_url}<br>Ответ: {resp.status_code}"

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print(f"🚀 Запуск на http://localhost:{port}")
    print(f"📤 Страница загрузки: http://localhost:{port}/upload")
    app.run(host='0.0.0.0', port=port, debug=True)
