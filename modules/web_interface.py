import os
import logging
from flask import render_template_string, request, jsonify, send_file, abort
from download_handler import DownloadHandler

logger = logging.getLogger(__name__)

# HTML шаблон для загрузки папок (упрощённая версия)
UPLOAD_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Загрузка объявлений</title>
    <style>
        body { font-family: Arial; max-width: 800px; margin: 50px auto; padding: 20px; }
        .container { border: 2px dashed #ccc; padding: 40px; text-align: center; border-radius: 10px; }
        .drop-zone { border: 2px dashed #007bff; padding: 40px; margin: 20px 0; border-radius: 10px; background: #f8f9fa; }
        .drop-zone.dragover { background: #e3f2fd; border-color: #0056b3; }
        input[type="file"] { display: none; }
        .btn { background: #007bff; color: white; padding: 12px 30px; border: none; border-radius: 5px; cursor: pointer; font-size: 16px; }
        .btn:hover { background: #0056b3; }
        .btn-success { background: #28a745; }
        .btn-success:hover { background: #218838; }
        .status { margin-top: 20px; padding: 15px; border-radius: 5px; display: none; }
        .status.success { background: #d4edda; color: #155724; display: block; }
        .status.error { background: #f8d7da; color: #721c24; display: block; }
        .status.info { background: #d1ecf1; color: #0c5460; display: block; }
        .file-list { text-align: left; margin: 20px 0; padding: 0; list-style: none; }
        .file-list li { background: #f8f9fa; padding: 10px; margin: 5px 0; border-radius: 5px; border-left: 3px solid #007bff; }
        .progress-bar { width: 100%; height: 20px; background: #e9ecef; border-radius: 10px; overflow: hidden; margin: 10px 0; display: none; }
        .progress-bar .progress { height: 100%; background: #28a745; transition: width 0.3s; width: 0%; }
        .instructions { background: #fff3cd; padding: 15px; border-radius: 5px; margin: 20px 0; text-align: left; border-left: 4px solid #ffc107; }
        .instructions code { background: #f8f9fa; padding: 2px 6px; border-radius: 3px; font-size: 14px; }
        #log { background: #1e1e1e; color: #d4d4d4; padding: 15px; border-radius: 5px; font-family: monospace; font-size: 12px; max-height: 300px; overflow-y: auto; margin: 20px 0; display: none; white-space: pre-wrap; }
    </style>
</head>
<body>
    <h1>📤 Загрузка объявлений</h1>
    
    <div class="instructions">
        <strong>📌 Инструкция:</strong><br>
        1. Подготовьте папку с объявлениями<br>
        2. Внутри папки должны быть подпапки с названиями типа: <code>Название -123456789</code><br>
        3. В каждой подпапке: <code>info.txt</code> (текст объявления) и изображения<br>
        4. Выберите папку и нажмите "Загрузить"
    </div>
    
    <div class="container">
        <div class="drop-zone" id="dropZone">
            <p>📂 Перетащите папку сюда</p>
            <p>или</p>
            <button class="btn" onclick="document.getElementById('folderInput').click()">Выбрать папку</button>
            <input type="file" id="folderInput" webkitdirectory multiple>
        </div>
        
        <div id="fileList" style="display:none;">
            <h4>📄 Выбранные файлы:</h4>
            <ul class="file-list" id="fileListContent"></ul>
            <button class="btn btn-success" onclick="uploadFolder()">🚀 Загрузить</button>
            <button class="btn" onclick="clearFiles()" style="background: #dc3545;">Очистить</button>
        </div>
        
        <div class="progress-bar" id="progressBar">
            <div class="progress" id="progress"></div>
        </div>
        
        <div id="status" class="status"></div>
        <div id="log"></div>
    </div>

    <script>
        let selectedFiles = [];
        let userId = 151296248;

        const dropZone = document.getElementById('dropZone');
        const folderInput = document.getElementById('folderInput');
        const fileList = document.getElementById('fileList');
        const fileListContent = document.getElementById('fileListContent');
        const statusDiv = document.getElementById('status');
        const logDiv = document.getElementById('log');
        const progressBar = document.getElementById('progressBar');
        const progress = document.getElementById('progress');

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
            files.forEach(f => {
                const parts = f.webkitRelativePath.split('/');
                if (parts.length > 1) {
                    folders.add(parts[0]);
                }
            });
            
            folders.forEach(folder => {
                const li = document.createElement('li');
                const count = files.filter(f => f.webkitRelativePath.startsWith(folder + '/')).length;
                li.textContent = `📁 ${folder} (${count} файлов)`;
                fileListContent.appendChild(li);
            });
            
            fileList.style.display = 'block';
            showStatus('info', `✅ Выбрано ${folders.size} папок, ${files.length} файлов`);
        }

        function clearFiles() {
            selectedFiles = [];
            fileList.style.display = 'none';
            statusDiv.style.display = 'none';
            progressBar.style.display = 'none';
            logDiv.style.display = 'none';
            folderInput.value = '';
        }

        function addLog(message) {
            logDiv.style.display = 'block';
            logDiv.textContent += message + '\\n';
            logDiv.scrollTop = logDiv.scrollHeight;
        }

        async function uploadFolder() {
            if (selectedFiles.length === 0) {
                showStatus('error', '❌ Выберите папку для загрузки');
                return;
            }

            const formData = new FormData();
            selectedFiles.forEach(file => {
                formData.append('files[]', file, file.webkitRelativePath);
            });
            formData.append('user_id', userId);

            showStatus('info', '⏳ Загрузка началась...');
            progressBar.style.display = 'block';
            progress.style.width = '0%';
            logDiv.textContent = '';
            addLog('🚀 Начинаем загрузку...');
            addLog(`📁 Файлов: ${selectedFiles.length}`);

            try {
                const xhr = new XMLHttpRequest();
                
                xhr.upload.addEventListener('progress', (e) => {
                    if (e.lengthComputable) {
                        const percent = (e.loaded / e.total) * 100;
                        progress.style.width = percent + '%';
                        addLog(`📥 Загружено: ${(e.loaded / 1024 / 1024).toFixed(1)} МБ из ${(e.total / 1024 / 1024).toFixed(1)} МБ (${Math.round(percent)}%)`);
                    }
                });

                xhr.onload = function() {
                    if (xhr.status === 200) {
                        try {
                            const response = JSON.parse(xhr.responseText);
                            if (response.success) {
                                showStatus('success', '✅ Загрузка завершена!');
                                addLog('✅ ' + response.message);
                                progress.style.width = '100%';
                            } else {
                                showStatus('error', '❌ ' + response.message);
                                addLog('❌ Ошибка: ' + response.message);
                            }
                        } catch (e) {
                            showStatus('error', '❌ Ошибка обработки ответа');
                            addLog('❌ Ошибка: ' + e.message);
                        }
                    } else {
                        showStatus('error', '❌ Ошибка загрузки: ' + xhr.status);
                        addLog('❌ Ошибка сервера: ' + xhr.status);
                    }
                };

                xhr.onerror = function() {
                    showStatus('error', '❌ Ошибка соединения');
                    addLog('❌ Ошибка соединения с сервером');
                };

                xhr.open('POST', '/upload_folder');
                xhr.send(formData);
                
            } catch (error) {
                showStatus('error', '❌ Ошибка: ' + error.message);
                addLog('❌ Ошибка: ' + error.message);
            }
        }

        function showStatus(type, message) {
            statusDiv.className = 'status ' + type;
            statusDiv.textContent = message;
            statusDiv.style.display = 'block';
        }
    </script>
</body>
</html>
"""

class WebInterface:
    def __init__(self, file_manager, publisher, download_handler):
        self.fm = file_manager
        self.publisher = publisher
        self.download_handler = download_handler
    
    def upload_page(self):
        """Возвращает HTML страницу для загрузки папок"""
        return render_template_string(UPLOAD_TEMPLATE)
    
    def upload_file(self, request, user_id):
        """Обработка загрузки папки"""
        try:
            files = request.files.getlist('files[]')
            if not files:
                return {'success': False, 'message': 'Файлы не выбраны'}
            
            result = self.fm.save_uploaded_files(files, user_id)
            if result['success']:
                # Запускаем публикацию
                self.publisher.start(user_id)
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки: {e}")
            return {'success': False, 'message': str(e)}
    
    def download_report(self, user_id, filename):
        """Обработка скачивания отчета"""
        try:
            filepath, error = self.download_handler.download_file(user_id, filename)
            
            if error:
                return jsonify({'success': False, 'message': error}), 404
            
            # Отправляем файл
            return send_file(
                filepath,
                as_attachment=True,
                download_name=filename,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )
            
        except Exception as e:
            logger.error(f"❌ Ошибка скачивания: {e}")
            return jsonify({'success': False, 'message': str(e)}), 500
