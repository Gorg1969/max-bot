from flask import render_template_string, request, jsonify
import os
import logging
import io
import zipfile

logger = logging.getLogger(__name__)

UPLOAD_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Загрузка архива</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 600px;
            margin: 50px auto;
            padding: 20px;
            background: #f5f5f5;
        }
        .container {
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        h1 { color: #333; text-align: center; }
        .info {
            background: #e8f4f8;
            padding: 15px;
            border-radius: 5px;
            margin: 20px 0;
            font-size: 14px;
        }
        .info code { background: #d0e4ed; padding: 2px 6px; border-radius: 3px; }
        .auth-section {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 5px;
            margin: 15px 0;
            text-align: center;
        }
        .auth-section .status {
            font-size: 14px;
            margin-bottom: 10px;
        }
        .auth-section .status.connected { color: #28a745; }
        .auth-section .status.disconnected { color: #dc3545; }
        .btn {
            display: inline-block;
            padding: 10px 20px;
            background: #4285F4;
            color: white;
            border: none;
            border-radius: 5px;
            font-size: 14px;
            cursor: pointer;
            text-decoration: none;
        }
        .btn:hover { background: #357ae8; }
        .btn-success { background: #28a745; }
        .btn-success:hover { background: #218838; }
        .btn-secondary { background: #6c757d; }
        .btn-secondary:hover { background: #5a6268; }
        .file-input-wrapper {
            margin: 20px 0;
            padding: 30px;
            border: 2px dashed #ccc;
            border-radius: 10px;
            text-align: center;
            cursor: pointer;
        }
        .file-input-wrapper:hover { border-color: #4CAF50; }
        .file-input-wrapper input[type="file"] { display: none; }
        .file-input-wrapper label { cursor: pointer; font-size: 16px; color: #666; }
        .file-input-wrapper.disabled { opacity: 0.5; cursor: not-allowed; pointer-events: none; }
        .file-input-wrapper.disabled:hover { border-color: #ccc; }
        .btn-upload {
            display: block;
            width: 100%;
            padding: 12px;
            background: #4CAF50;
            color: white;
            border: none;
            border-radius: 5px;
            font-size: 16px;
            cursor: pointer;
            margin-top: 10px;
        }
        .btn-upload:hover { background: #45a049; }
        .btn-upload:disabled { background: #ccc; cursor: not-allowed; }
        .progress-bar {
            width: 100%;
            background: #f0f0f0;
            border-radius: 5px;
            margin: 10px 0;
            display: none;
        }
        .progress-bar .progress {
            width: 0%;
            height: 20px;
            background: #4CAF50;
            border-radius: 5px;
            text-align: center;
            line-height: 20px;
            color: white;
            font-size: 12px;
        }
        .status-msg { margin-top: 20px; padding: 15px; border-radius: 5px; display: none; }
        .status-msg.success { display: block; background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .status-msg.error { display: block; background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        .status-msg.info { display: block; background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
        .footer { text-align: center; margin-top: 20px; font-size: 12px; color: #999; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📤 Загрузка архива</h1>
        
        <div class="auth-section">
            <div id="authStatus" class="status disconnected">⏳ Проверка подключения...</div>
            <div>
                <button id="checkAuthBtn" class="btn btn-secondary">🔄 Проверить подключение</button>
                <a id="authLink" href="/auth?user_id=151296248" target="_blank" class="btn" style="display: none;">🔐 Подключить Google Диск</a>
            </div>
        </div>
        
        <div class="info">
            <strong>📌 Требования к архиву:</strong><br>
            • Формат: <code>.zip</code><br>
            • Внутри папки с названиями: <code>Название -123456789</code><br>
            • В каждой папке: <code>info.txt</code> и изображения<br>
            • <strong>Ограничений на размер нет</strong>
        </div>
        
        <div class="file-input-wrapper" id="fileWrapper" onclick="document.getElementById('fileInput').click()">
            <input type="file" id="fileInput" name="file" accept=".zip">
            <label for="fileInput">📂 <strong>Выберите ZIP-архив</strong><br>
            <span style="font-size: 14px; color: #999;">(просто нажмите и выберите файл)</span></label>
        </div>
        
        <div id="progressBar" class="progress-bar">
            <div id="progress" class="progress">0%</div>
        </div>
        
        <button class="btn-upload" id="submitBtn" disabled>📤 Загрузить и опубликовать</button>
        <div id="statusMsg" class="status-msg"></div>
        <div class="footer">Бот автоматически начнёт публикацию после загрузки</div>
    </div>

    <script>
        let isAuthorized = false;
        
        async function checkAuth() {
            const statusDiv = document.getElementById('authStatus');
            const authLink = document.getElementById('authLink');
            const fileWrapper = document.getElementById('fileWrapper');
            const submitBtn = document.getElementById('submitBtn');
            
            statusDiv.textContent = '⏳ Проверка...';
            statusDiv.className = 'status';
            
            try {
                const response = await fetch('/check_auth?user_id=151296248');
                const data = await response.json();
                
                if (data.authorized) {
                    isAuthorized = true;
                    statusDiv.textContent = '✅ Google Диск подключён';
                    statusDiv.className = 'status connected';
                    authLink.style.display = 'none';
                    fileWrapper.classList.remove('disabled');
                    if (document.getElementById('fileInput').files.length > 0) {
                        submitBtn.disabled = false;
                    }
                } else {
                    isAuthorized = false;
                    statusDiv.textContent = '❌ Google Диск не подключён';
                    statusDiv.className = 'status disconnected';
                    authLink.style.display = 'inline-block';
                    fileWrapper.classList.add('disabled');
                    submitBtn.disabled = true;
                }
            } catch (e) {
                statusDiv.textContent = '❌ Ошибка проверки';
                statusDiv.className = 'status disconnected';
            }
        }
        
        checkAuth();
        document.getElementById('checkAuthBtn').addEventListener('click', checkAuth);
        
        document.getElementById('fileInput').addEventListener('change', function() {
            const file = this.files[0];
            const submitBtn = document.getElementById('submitBtn');
            
            if (file && isAuthorized) {
                submitBtn.disabled = false;
                showStatus('✅ Выбран файл: ' + file.name + ' (' + (file.size / 1024 / 1024).toFixed(1) + ' МБ)', 'info');
            } else if (!isAuthorized) {
                showStatus('❌ Сначала подключите Google Диск', 'error');
            } else {
                submitBtn.disabled = true;
                showStatus('', '');
            }
        });
        
        document.getElementById('submitBtn').addEventListener('click', async function() {
            const fileInput = document.getElementById('fileInput');
            const submitBtn = this;
            const progressBar = document.getElementById('progressBar');
            const progress = document.getElementById('progress');
            
            if (!fileInput.files.length) {
                showStatus('❌ Выберите файл для загрузки', 'error');
                return;
            }
            
            const file = fileInput.files[0];
            if (!file.name.endsWith('.zip')) {
                showStatus('❌ Файл должен быть в формате .zip', 'error');
                return;
            }
            
            submitBtn.disabled = true;
            submitBtn.textContent = '⏳ Загрузка...';
            progressBar.style.display = 'block';
            showStatus('⏳ Загрузка файла на Google Диск...', 'info');
            
            try {
                const formData = new FormData();
                formData.append('file', file);
                formData.append('user_id', '151296248');
                
                const response = await fetch('/upload_to_drive', {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                
                if (result.success) {
                    progress.style.width = '100%';
                    progress.textContent = '100%';
                    showStatus('✅ ' + result.message, 'success');
                } else {
                    showStatus('❌ ' + result.message, 'error');
                }
            } catch (error) {
                showStatus('❌ Ошибка загрузки: ' + error.message, 'error');
            } finally {
                submitBtn.disabled = false;
                submitBtn.textContent = '📤 Загрузить и опубликовать';
            }
        });
        
        function showStatus(message, type) {
            const statusDiv = document.getElementById('statusMsg');
            statusDiv.textContent = message;
            statusDiv.className = 'status-msg ' + (type || '');
        }
    </script>
</body>
</html>
"""

class WebInterface:
    def __init__(self, file_manager, publisher):
        self.fm = file_manager
        self.publisher = publisher
    
    def upload_page(self):
        return render_template_string(UPLOAD_HTML)
    
    def upload_to_drive(self, request, user_id, drive):
        """Загрузка файла на Google Диск пользователя"""
        if 'file' not in request.files:
            return {'success': False, 'message': 'Файл не выбран'}
        
        file = request.files['file']
        if file.filename == '':
            return {'success': False, 'message': 'Файл не выбран'}
        
        if not file.filename.endswith('.zip'):
            return {'success': False, 'message': 'Файл должен быть в формате .zip'}
        
        # Создаём временную папку на Google Диске
        temp_folder_id = drive.create_temp_folder(user_id)
        if not temp_folder_id:
            return {'success': False, 'message': 'Не удалось создать временную папку на Google Диске'}
        
        # Загружаем файл
        file_id = drive.save_file_to_temp(file, file.filename, temp_folder_id)
        if not file_id:
            return {'success': False, 'message': 'Не удалось загрузить файл на Google Диск'}
        
        logger.info(f"✅ Файл загружен на Google Диск: {file.filename}")
        
        # Запускаем публикацию
        self.publisher.start_from_drive(user_id, temp_folder_id)
        return {'success': True, 'message': f'Файл загружен на Google Диск. Публикация началась!'}
