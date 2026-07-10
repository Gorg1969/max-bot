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
        .status { margin-top: 20px; padding: 15px; border-radius: 5px; display: none; }
        .status.success { display: block; background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
        .status.error { display: block; background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
        .status.info { display: block; background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
        .footer { text-align: center; margin-top: 20px; font-size: 12px; color: #999; }
        .auth-warning {
            background: #fff3cd;
            border: 1px solid #ffeeba;
            padding: 15px;
            border-radius: 5px;
            margin: 15px 0;
            color: #856404;
        }
        .auth-warning a { color: #4CAF50; font-weight: bold; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📤 Загрузка архива</h1>
        
        <div id="authWarning" class="auth-warning" style="display: none;">
            ⚠️ <strong>Google Диск не подключён!</strong><br>
            Для загрузки архива необходимо подключить Google Диск.
            <a href="/auth?user_id=151296248" target="_blank">Подключить Google Диск</a>
        </div>
        
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
        
        <div id="progressBar" class="progress-bar">
            <div id="progress" class="progress">0%</div>
        </div>
        
        <button class="btn" id="submitBtn" disabled>📤 Загрузить и опубликовать</button>
        
        <div id="status" class="status"></div>
        <div class="footer">Бот автоматически начнёт публикацию после загрузки</div>
    </div>

    <script>
        // Проверяем авторизацию при загрузке страницы
        async function checkAuth() {
            try {
                const response = await fetch('/check_auth?user_id=151296248');
                const data = await response.json();
                if (!data.authorized) {
                    document.getElementById('authWarning').style.display = 'block';
                }
            } catch (e) {
                console.error('Ошибка проверки авторизации:', e);
            }
        }
        checkAuth();
        
        const CHUNK_SIZE = 10 * 1024 * 1024; // 10 МБ
        
        document.getElementById('fileInput').addEventListener('change', function() {
            const file = this.files[0];
            const submitBtn = document.getElementById('submitBtn');
            
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
            showStatus('⏳ Загрузка файла...', 'info');
            
            const totalChunks = Math.ceil(file.size / CHUNK_SIZE);
            const uploadedChunks = [];
            
            for (let i = 0; i < totalChunks; i++) {
                const start = i * CHUNK_SIZE;
                const end = Math.min(start + CHUNK_SIZE, file.size);
                const chunk = file.slice(start, end);
                
                const formData = new FormData();
                formData.append('chunk', chunk);
                formData.append('chunkIndex', i);
                formData.append('totalChunks', totalChunks);
                formData.append('filename', file.name);
                formData.append('user_id', '151296248');
                
                try {
                    const response = await fetch('/upload_chunk', {
                        method: 'POST',
                        body: formData
                    });
                    
                    const result = await response.json();
                    
                    if (result.success) {
                        uploadedChunks.push(i);
                        const percent = Math.round((uploadedChunks.length / totalChunks) * 100);
                        progress.style.width = percent + '%';
                        progress.textContent = percent + '%';
                    } else {
                        throw new Error(result.message);
                    }
                } catch (error) {
                    showStatus('❌ Ошибка загрузки: ' + error.message, 'error');
                    submitBtn.disabled = false;
                    submitBtn.textContent = '📤 Загрузить и опубликовать';
                    return;
                }
            }
            
            // Все части загружены — собираем файл
            showStatus('⏳ Сборка файла...', 'info');
            
            try {
                const response = await fetch('/assemble_file', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        filename: file.name,
                        user_id: '151296248',
                        totalChunks: totalChunks
                    })
                });
                
                const result = await response.json();
                
                if (result.success) {
                    showStatus('✅ ' + result.message, 'success');
                } else {
                    showStatus('❌ ' + result.message, 'error');
                }
            } catch (error) {
                showStatus('❌ Ошибка сборки: ' + error.message, 'error');
            } finally {
                submitBtn.disabled = false;
                submitBtn.textContent = '📤 Загрузить и опубликовать';
                progress.style.width = '100%';
                progress.textContent = '100%';
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
    
    def upload_chunk(self, request, user_id):
        if 'chunk' not in request.files:
            return {'success': False, 'message': 'Нет части файла'}
        
        chunk = request.files['chunk']
        chunk_index = int(request.form.get('chunkIndex', 0))
        total_chunks = int(request.form.get('totalChunks', 0))
        filename = request.form.get('filename', 'temp.zip')
        
        user_folder = self.fm.get_user_folder(user_id)
        chunk_dir = os.path.join(user_folder, 'chunks')
        os.makedirs(chunk_dir, exist_ok=True)
        
        chunk_path = os.path.join(chunk_dir, f'chunk_{chunk_index}')
        chunk.save(chunk_path)
        
        logger.info(f"📥 Часть {chunk_index+1}/{total_chunks} сохранена")
        return {'success': True}
    
    def assemble_file(self, request, user_id):
        data = request.get_json()
        filename = data.get('filename', 'temp.zip')
        total_chunks = data.get('totalChunks', 0)
        
        user_folder = self.fm.get_user_folder(user_id)
        chunk_dir = os.path.join(user_folder, 'chunks')
        output_path = os.path.join(user_folder, filename)
        
        try:
            with open(output_path, 'wb') as outfile:
                for i in range(total_chunks):
                    chunk_path = os.path.join(chunk_dir, f'chunk_{i}')
                    if not os.path.exists(chunk_path):
                        return {'success': False, 'message': f'Часть {i+1} не найдена'}
                    
                    with open(chunk_path, 'rb') as infile:
                        outfile.write(infile.read())
                    os.remove(chunk_path)
            
            os.rmdir(chunk_dir)
            
            logger.info(f"✅ Файл собран: {output_path} ({os.path.getsize(output_path)} байт)")
            
            if self.fm.extract_zip(user_id, output_path):
                os.remove(output_path)
                self.publisher.start(user_id)
                return {'success': True, 'message': 'Архив распакован. Публикация началась!'}
            else:
                self.fm.clear_user_data(user_id)
                return {'success': False, 'message': 'Ошибка распаковки архива'}
        except Exception as e:
            logger.error(f"❌ Ошибка сборки: {e}")
            return {'success': False, 'message': f'Ошибка: {str(e)}'}
