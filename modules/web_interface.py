from flask import render_template_string, request, jsonify
import os
import logging
import zipfile
import io
import re
import tempfile

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
        .section {
            margin: 20px 0;
            padding: 15px;
            border: 1px solid #ddd;
            border-radius: 5px;
            background: #f9f9f9;
        }
        .section-title {
            font-weight: bold;
            margin-bottom: 10px;
            color: #333;
        }
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
        .link-input {
            width: 100%;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 5px;
            font-size: 14px;
            margin: 10px 0;
            box-sizing: border-box;
        }
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
        
        <!-- ТОЛЬКО ССЫЛКА НА GOOGLE DRIVE -->
        <div class="section">
            <div class="section-title">📎 Ссылка на Google Drive</div>
            <p style="font-size: 14px; color: #666; margin-bottom: 10px;">
                Вставьте ссылку на ZIP-архив, загруженный на Google Drive.
            </p>
            <input type="text" id="driveLink" class="link-input" placeholder="https://drive.google.com/file/d/.../view?usp=sharing">
            <button class="btn-upload" id="processDriveLinkBtn" style="background: #4285F4; margin-top: 0;">📥 Загрузить и опубликовать</button>
        </div>
        
        <div id="statusMsg" class="status-msg"></div>
        <div class="footer">Бот автоматически начнёт публикацию после загрузки</div>
    </div>

    <script>
        document.getElementById('processDriveLinkBtn').addEventListener('click', async function() {
            const linkInput = document.getElementById('driveLink');
            const statusDiv = document.getElementById('statusMsg');
            const link = linkInput.value.trim();
            
            if (!link) {
                showStatus('❌ Введите ссылку на архив', 'error');
                return;
            }
            
            if (!link.includes('drive.google.com')) {
                showStatus('❌ Ссылка должна быть на Google Drive', 'error');
                return;
            }
            
            showStatus('⏳ Обработка ссылки...', 'info');
            
            try {
                const response = await fetch('/process_drive_link', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: link, user_id: '151296248' })
                });
                
                const result = await response.json();
                
                if (result.success) {
                    showStatus('✅ ' + result.message, 'success');
                } else {
                    showStatus('❌ ' + result.message, 'error');
                }
            } catch (error) {
                showStatus('❌ Ошибка: ' + error.message, 'error');
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
