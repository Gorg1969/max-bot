from flask import render_template_string, request, jsonify
import os
import logging

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
        .file-input-wrapper {
            margin: 20px 0;
            padding: 30px;
            border: 2px dashed #ccc;
            border-radius: 10px;
            text-align: center;
            cursor: pointer;
        }
        .file-input-wrapper:hover { border-color: #4CAF50; }
        .file-input-wrapper input[type="file"] {
            display: none;
        }
        .file-input-wrapper label {
            cursor: pointer;
            font-size: 16px;
            color: #666;
        }
        .btn {
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
        .btn:hover { background: #45a049; }
        .btn:disabled { background: #ccc; cursor: not-allowed; }
        .status { margin-top: 20px; padding: 15px; border-radius: 5px; display: none; }
        .status.success { display: block; background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .status.error { display: block; background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        .status.info { display: block; background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
        .footer { text-align: center; margin-top: 20px; font-size: 12px; color: #999; }
        .help-link { text-align: center; margin-top: 15px; }
        .help-link a { color: #4CAF50; text-decoration: none; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📤 Загрузка архива</h1>
        <div class="info">
            <strong>📌 Требования к архиву:</strong><br>
            • Формат: <code>.zip</code><br>
            • Внутри папки с названиями: <code>Название -123456789</code><br>
            • В каждой папке: <code>info.txt</code> и изображения<br>
            • <strong>Ограничений на размер нет</strong>
        </div>
        
        <div class="file-input-wrapper" onclick="document.getElementById('fileInput').click()">
            <input type="file" id="fileInput" name="file" accept=".zip">
            <label for="fileInput">📂 <strong>Выберите ZIP-архив</strong><br>
            <span style="font-size: 14px; color: #999;">(просто нажмите и выберите файл)</span></label>
        </div>
        
        <button class="btn" id="submitBtn" disabled>📤 Загрузить и опубликовать</button>
        
        <div id="status" class="status"></div>
        
        <div class="help-link">
            <a href="/help" target="_blank">📖 Помощь</a>
        </div>
        
        <div class="footer">Бот автоматически начнёт публикацию после загрузки</div>
    </div>

    <script>
        document.getElementById('fileInput').addEventListener('change', function() {
            const file = this.files[0];
            const submitBtn = document.getElementById('submitBtn');
            const statusDiv = document.getElementById('status');
            
            if (file) {
                submitBtn.disabled = false;
                showStatus('✅ Выбран файл: ' + file.name + ' (' + (file.size / 1024 / 1024).toFixed(1) + ' МБ)', 'info');
            } else {
                submitBtn.disabled = true;
                showStatus('', '');
            }
        });
        
        document.getElementById('submitBtn').addEventListener('click', async function() {
            const fileInput = document.getElementById('fileInput');
            const submitBtn = this;
            const statusDiv = document.getElementById('status');
            
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
            showStatus('⏳ Загрузка файла...', 'info');
            
            const formData = new FormData();
            formData.append('file', file);
            
            try {
                const response = await fetch('/upload', {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                
                if (result.success) {
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
            const statusDiv = document.getElementById('status');
            statusDiv.textContent = message;
            statusDiv.className = 'status ' + (type || '');
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
    
    def upload_file(self, request, user_id):
        if 'file' not in request.files:
            return {'success': False, 'message': 'Файл не выбран'}
        
        file = request.files['file']
        if file.filename == '':
            return {'success': False, 'message': 'Файл не выбран'}
        
        if not file.filename.endswith('.zip'):
            return {'success': False, 'message': 'Файл должен быть в формате .zip'}
        
        user_folder = self.fm.get_user_folder(user_id)
        zip_path = os.path.join(user_folder, 'temp.zip')
        file.save(zip_path)
        
        if self.fm.extract_zip(user_id, zip_path):
            os.remove(zip_path)
            self.publisher.start(user_id)
            return {'success': True, 'message': 'Архив распакован. Публикация началась!'}
        else:
            self.fm.clear_user_data(user_id)
            return {'success': False, 'message': 'Ошибка распаковки архива'}
