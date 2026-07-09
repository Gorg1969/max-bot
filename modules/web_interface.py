from flask import render_template_string, request, jsonify
import os
import logging

logger = logging.getLogger(__name__)

# ========== СТРАНИЦА ПОМОЩИ (HTML) ==========
HELP_PAGE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Помощь - MAX Bot</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 800px;
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
        h1 { color: #333; }
        h2 { color: #4CAF50; margin-top: 30px; }
        .step {
            background: #e8f4f8;
            padding: 15px;
            border-radius: 5px;
            margin: 15px 0;
        }
        .step code {
            background: #d0e4ed;
            padding: 2px 6px;
            border-radius: 3px;
        }
        .example {
            background: #f0f0f0;
            padding: 15px;
            border-radius: 5px;
            margin: 10px 0;
            font-family: monospace;
            white-space: pre-wrap;
        }
        .footer {
            text-align: center;
            margin-top: 30px;
            font-size: 12px;
            color: #999;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>📖 Помощь</h1>
        
        <h2>📌 Как пользоваться ботом</h2>
        
        <div class="step">
            <strong>Шаг 1: Подготовьте архив</strong><br>
            • Формат: <code>.zip</code><br>
            • Внутри папки с названиями: <code>Название -123456789</code><br>
            • В каждой папке: <code>info.txt</code> и изображения<br>
            • <strong>Важно!</strong> ID группы в названии папки должен быть правильным.
        </div>
        
        <div class="step">
            <strong>Шаг 2: Загрузите архив</strong><br>
            • Откройте веб-интерфейс: <a href="/upload">/upload</a><br>
            • Нажмите "Выбрать файл" и выберите архив<br>
            • Нажмите "Загрузить и опубликовать"
        </div>
        
        <div class="step">
            <strong>Шаг 3: Ожидайте публикации</strong><br>
            • Бот автоматически найдёт папки с ID групп<br>
            • Публикация идёт с задержкой 1-3 минуты между постами<br>
            • После 10 постов — пауза 5 минут<br>
            • Вы получите уведомление о завершении
        </div>
        
        <h2>📝 Форматирование текста (Markdown)</h2>
        
        <div class="example">
<strong>Жирный</strong>: **текст** или __текст__<br>
<em>Курсив</em>: *текст* или _текст_<br>
<ins>Подчёркнутый</ins>: ++текст++<br>
<del>Зачёркнутый</del>: ~~текст~~<br>
<mark>Выделенный</mark>: ^^текст^^<br>
<code>Моноширинный</code>: `код`<br>
<strong>Гиперссылка</strong>: [Текст ссылки](https://example.com)<br>
<strong>Изображение</strong>: ![Описание](https://example.com/image.jpg)<br>
<strong>Заголовок</strong>: # Заголовок<br>
<blockquote>Цитата: > Текст цитаты</blockquote>
        </div>
        
        <div class="step">
            <strong>Пример info.txt с Markdown:</strong>
            <div class="example">
**Самосвал Howo T5G 8x4**

*Дизельный, 10,5 л, 440 л.с., МТ*

**Цена:** 4 781 000 руб с НДС

**Пробег:** 184 179 км  
**Год:** 2023  
**Место:** Уфа, ул. Рассветная, д 77/3

[Подробнее на сайте](https://example.com)
            </div>
        </div>
        
        <h2>⏹ Остановка публикации</h2>
        <div class="step">
            Отправьте боту команду <code>/stop</code> в MAX.
        </div>
        
        <div class="footer">
            MAX Bot v1.0 | © 2026
        </div>
    </div>
</body>
</html>
"""

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
        .file-input-wrapper { margin: 20px 0; }
        .file-input-wrapper input[type="file"] {
            display: block;
            width: 100%;
            padding: 10px;
            border: 2px dashed #ccc;
            border-radius: 5px;
            cursor: pointer;
        }
        .file-input-wrapper input[type="file"]:hover { border-color: #4CAF50; }
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
        .help-link a:hover { text-decoration: underline; }
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
        
        <form id="uploadForm" enctype="multipart/form-data">
            <div class="file-input-wrapper">
                <input type="file" id="fileInput" name="file" accept=".zip" required>
            </div>
            <button type="submit" class="btn" id="submitBtn">📤 Загрузить и опубликовать</button>
        </form>
        
        <div id="status" class="status"></div>
        
        <div class="help-link">
            <a href="/help" target="_blank">📖 Помощь</a>
        </div>
        
        <div class="footer">Бот автоматически начнёт публикацию после загрузки</div>
    </div>

    <script>
        document.getElementById('uploadForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const fileInput = document.getElementById('fileInput');
            const submitBtn = document.getElementById('submitBtn');
            const statusDiv = document.getElementById('status');
            
            if (!fileInput.files.length) {
                showStatus('Выберите файл для загрузки', 'error');
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
            statusDiv.className = 'status ' + type;
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
    
    def help_page(self):
        return render_template_string(HELP_PAGE)
    
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
