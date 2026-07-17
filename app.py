# app.py

from flask import Flask, request, jsonify, render_template_string, send_file
import os
import logging
import json
from rq import Queue
from rq.job import Job
from redis import Redis
from modules import Database, FileManager, Publisher
from modules.report_generator import ReportGenerator
from modules.tasks import process_folder_task, cleanup_user_task

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key")
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация
DATA_DIR = "/app/data"
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
TOKEN = os.environ.get("MAX_TOKEN") or os.environ.get("MAX_BOT_TOKEN") or os.environ.get("TOKEN")

if not TOKEN:
    logger.error("❌ ТОКЕН НЕ НАЙДЕН!")

# Инициализация RQ
redis_conn = Redis.from_url(REDIS_URL)
queue = Queue('default', connection=redis_conn)

# Инициализация БД и менеджеров (только для веб-части)
db = Database()
fm = FileManager(DATA_DIR)
report_gen = ReportGenerator(fm, db)

# ========== HTML СТРАНИЦА ==========
UPLOAD_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Загрузка объявлений</title>
    <style>
        /* ... ваш CSS ... */
    </style>
</head>
<body>
    <!-- ... ваш HTML ... -->
    <script>
        // ОБНОВЛЕННЫЙ JavaScript с использованием FormData
        
        const urlParams = new URLSearchParams(window.location.search);
        const userId = urlParams.get('user_id') || 151296248;
        let jobIds = [];
        let isProcessing = false;
        let isStopped = false;
        let folderQueue = [];
        let processedCount = 0;
        let totalFolders = 0;
        let jobStatusInterval = null;
        
        // ... функции displayFiles, addLog, showStatus, updateQueueStatus ...
        
        async function uploadFolder() {
            if (selectedFiles.length === 0) {
                showStatus('error', '❌ Выберите папку для загрузки');
                return;
            }
            
            if (isProcessing) {
                addLog('⚠️ Обработка уже выполняется, подождите...');
                return;
            }
            
            const maxPhotos = parseInt(document.getElementById('maxPhotos').value) || 6;
            const delayBetween = parseInt(document.getElementById('delayBetween').value) || 3;
            
            isProcessing = true;
            isStopped = false;
            processedCount = 0;
            jobIds = [];
            
            showStatus('info', '⏳ Подготовка данных...');
            progressBar.style.display = 'block';
            progress.style.width = '0%';
            progress.textContent = '0%';
            logDiv.textContent = '';
            addLog('🚀 Начинаем обработку...');
            
            // Группируем файлы по папкам
            const folders = {};
            selectedFiles.forEach(file => {
                const pathParts = file.webkitRelativePath.split('/');
                if (pathParts.length >= 2) {
                    const folderName = pathParts[0] + '/' + pathParts[1];
                    if (!folders[folderName]) {
                        folders[folderName] = [];
                    }
                    folders[folderName].push(file);
                }
            });
            
            const folderNames = Object.keys(folders);
            totalFolders = folderNames.length;
            
            folderQueue = folderNames.map(name => ({
                name: name,
                status: 'pending'
            }));
            updateQueueStatus();
            
            addLog(`📁 Найдено ${totalFolders} папок`);
            
            // Создаем FormData и отправляем все папки
            const formData = new FormData();
            formData.append('user_id', userId);
            formData.append('max_photos', maxPhotos);
            formData.append('delay_between', delayBetween);
            formData.append('total_folders', totalFolders);
            
            // Добавляем файлы с указанием папки
            selectedFiles.forEach(file => {
                const pathParts = file.webkitRelativePath.split('/');
                if (pathParts.length >= 2) {
                    const folderName = pathParts[0] + '/' + pathParts[1];
                    // Добавляем файл с путем к папке
                    formData.append('files[]', file, `${folderName}/${file.name}`);
                }
            });
            
            addLog(`📤 Отправка ${selectedFiles.length} файлов на сервер...`);
            
            try {
                const response = await fetch('/upload_folders', {
                    method: 'POST',
                    body: formData
                });
                
                if (!response.ok) {
                    const text = await response.text();
                    throw new Error(`HTTP ${response.status}: ${text.substring(0, 100)}`);
                }
                
                const result = await response.json();
                
                if (!result.success) {
                    throw new Error(result.message || 'Ошибка загрузки');
                }
                
                jobIds = result.job_ids || [];
                addLog(`✅ Создано ${jobIds.length} задач`);
                
                if (jobIds.length === 0) {
                    showStatus('error', '❌ Не создано ни одной задачи');
                    isProcessing = false;
                    return;
                }
                
                // Запускаем мониторинг статуса
                startJobMonitoring();
                
            } catch (error) {
                addLog(`❌ Ошибка: ${error.message}`);
                showStatus('error', `❌ Ошибка: ${error.message}`);
                isProcessing = false;
            }
        }
        
        function startJobMonitoring() {
            if (jobStatusInterval) {
                clearInterval(jobStatusInterval);
            }
            
            jobStatusInterval = setInterval(async () => {
                try {
                    const response = await fetch('/job_status', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ job_ids: jobIds })
                    });
                    
                    if (!response.ok) return;
                    
                    const data = await response.json();
                    
                    // Обновляем статусы
                    let completed = 0;
                    let failed = 0;
                    let finished = 0;
                    
                    jobIds.forEach(jobId => {
                        const status = data[jobId];
                        if (status) {
                            if (status.status === 'finished') {
                                finished++;
                                if (status.result && status.result.success) {
                                    completed++;
                                    // Обновляем статус папки
                                    const folderName = status.result.folder_name;
                                    const index = folderQueue.findIndex(f => f.name === folderName);
                                    if (index !== -1) {
                                        folderQueue[index].status = 'done';
                                    }
                                } else {
                                    failed++;
                                    const folderName = status.result ? status.result.folder_name : 'unknown';
                                    const index = folderQueue.findIndex(f => f.name === folderName);
                                    if (index !== -1) {
                                        folderQueue[index].status = 'error';
                                    }
                                }
                            } else if (status.status === 'failed') {
                                failed++;
                            }
                        }
                    });
                    
                    processedCount = completed + failed;
                    updateQueueStatus();
                    
                    // Обновляем прогресс
                    const progressPercent = Math.round((processedCount / totalFolders) * 100);
                    progress.style.width = progressPercent + '%';
                    progress.textContent = `${progressPercent}%`;
                    
                    // Проверяем завершение
                    if (finished >= jobIds.length) {
                        clearInterval(jobStatusInterval);
                        jobStatusInterval = null;
                        isProcessing = false;
                        
                        if (failed === 0 && completed === totalFolders) {
                            showStatus('success', `✅ Загружено ${completed} папок!`);
                            addLog(`✅ ВСЕ ${completed} папок загружены!`);
                        } else {
                            showStatus('warning', `⚠️ Загружено ${completed} папок, ${failed} с ошибками`);
                            addLog(`⚠️ Загружено ${completed} папок, ${failed} с ошибками`);
                        }
                        
                        if (completed > 0) {
                            addLog(`\\n📊 Скачать отчет: /report/${userId}`);
                        }
                    }
                    
                } catch (error) {
                    console.error('Ошибка мониторинга:', error);
                }
            }, 2000);
        }
        
        function stopPublish() {
            isStopped = true;
            isProcessing = false;
            addLog('⏹️ Публикация остановлена пользователем');
            showStatus('warning', '⏹️ Публикация остановлена');
            
            if (jobStatusInterval) {
                clearInterval(jobStatusInterval);
                jobStatusInterval = null;
            }
            
            fetch('/stop_publish', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    user_id: parseInt(userId),
                    job_ids: jobIds 
                })
            }).catch(e => console.error('Ошибка остановки:', e));
        }
        
        function getReport() {
            window.open(`/report/${userId}`, '_blank');
        }
        
        function clearFiles() {
            if (isProcessing) {
                if (!confirm('Остановить публикацию и очистить?')) return;
                stopPublish();
            }
            selectedFiles = [];
            folderQueue = [];
            jobIds = [];
            processedCount = 0;
            totalFolders = 0;
            fileList.style.display = 'none';
            statusDiv.style.display = 'none';
            progressBar.style.display = 'none';
            logDiv.style.display = 'none';
            progress.style.width = '0%';
            progress.textContent = '0%';
            folderInput.value = '';
            isStopped = false;
            if (jobStatusInterval) {
                clearInterval(jobStatusInterval);
                jobStatusInterval = null;
            }
        }
        
        // Остальные функции (readDirectory, displayFiles, updateQueueStatus, updateFolderStatus) остаются без изменений
    </script>
</body>
</html>
"""

# ========== МАРШРУТЫ ==========

@app.route('/')
def index():
    return "🤖 MAX Bot is running!"

@app.route('/upload', methods=['GET'])
def upload_page():
    return render_template_string(UPLOAD_PAGE)

@app.route('/upload_folders', methods=['POST'])
def upload_folders():
    """Принимает FormData с файлами и создает задачи в RQ"""
    try:
        user_id = request.form.get('user_id', type=int)
        max_photos = request.form.get('max_photos', 6, type=int)
        delay_between = request.form.get('delay_between', 3, type=int)
        total_folders = request.form.get('total_folders', 0, type=int)
        
        if not user_id:
            return jsonify({'success': False, 'message': 'Нет user_id'}), 400
        
        files = request.files.getlist('files[]')
        if not files:
            return jsonify({'success': False, 'message': 'Нет файлов'}), 400
        
        logger.info(f"📦 Получено {len(files)} файлов от пользователя {user_id}")
        
        # Группируем файлы по папкам
        folders = {}
        for file in files:
            # Путь в формате "folder_name/filename"
            file_path = file.filename
            if '/' in file_path:
                folder_name = file_path.split('/')[0]
                if folder_name not in folders:
                    folders[folder_name] = []
                folders[folder_name].append(file)
        
        logger.info(f"📁 Найдено {len(folders)} папок")
        
        # Обрабатываем каждую папку
        job_ids = []
        folder_data_list = []
        
        for folder_name, folder_files in folders.items():
            # Находим info.txt
            info_file = None
            image_files = []
            
            for f in folder_files:
                if f.filename.endswith('.txt') and 'info' in f.filename.lower():
                    info_file = f
                elif f.filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.bmp')):
                    image_files.append(f)
            
            if not info_file:
                logger.warning(f"⚠️ Нет info.txt в папке {folder_name}")
                continue
            
            # Читаем текст
            try:
                info_content = info_file.read().decode('utf-8')
            except Exception as e:
                logger.error(f"❌ Ошибка чтения info.txt: {e}")
                continue
            
            # Разделяем текст
            ad_text = info_content
            metadata_text = ''
            if '#изъятая' in info_content:
                parts = info_content.split('#изъятая')
                ad_text = parts[0].strip()
                metadata_text = parts[1] if len(parts) > 1 else ''
            
            # Ограничиваем количество фото
            image_files = image_files[:max_photos]
            
            # Читаем изображения
            images = []
            for img_file in image_files:
                try:
                    img_data = img_file.read()
                    images.append({
                        'name': img_file.filename,
                        'data': list(img_data),
                        'type': img_file.content_type or 'image/jpeg'
                    })
                except Exception as e:
                    logger.error(f"❌ Ошибка чтения {img_file.filename}: {e}")
            
            # Подготавливаем данные для задачи
            folder_data = {
                'folderName': folder_name,
                'adText': ad_text,
                'metadataText': metadata_text,
                'images': images
            }
            
            folder_data_list.append(folder_data)
        
        # Создаем задачи в RQ
        for folder_data in folder_data_list:
            job = queue.enqueue(
                process_folder_task,
                user_id,
                folder_data,
                job_id=None,  # RQ сам создаст ID
                result_ttl=3600,  # Храним результат 1 час
                failure_ttl=3600,
                timeout=300  # 5 минут на задачу
            )
            job_ids.append(job.id)
            logger.info(f"📝 Создана задача {job.id} для папки {folder_data['folderName']}")
        
        return jsonify({
            'success': True,
            'message': f'Создано {len(job_ids)} задач',
            'job_ids': job_ids,
            'total_folders': len(folder_data_list)
        })
        
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/job_status', methods=['POST'])
def job_status():
    """Получение статуса задач"""
    try:
        data = request.get_json()
        job_ids = data.get('job_ids', [])
        
        if not job_ids:
            return jsonify({})
        
        result = {}
        for job_id in job_ids:
            try:
                job = Job.fetch(job_id, connection=redis_conn)
                status = {
                    'status': job.get_status(),
                    'created_at': job.created_at.isoformat() if job.created_at else None,
                }
                
                if job.is_finished:
                    status['result'] = job.return_value()
                elif job.is_failed:
                    status['error'] = str(job.exc_info)
                
                result[job_id] = status
            except Exception as e:
                logger.warning(f"⚠️ Задача {job_id} не найдена: {e}")
                result[job_id] = {'status': 'unknown'}
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения статуса: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/stop_publish', methods=['POST'])
def stop_publish():
    """Остановка публикации"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        job_ids = data.get('job_ids', [])
        
        if not user_id:
            return jsonify({'success': False, 'message': 'Нет user_id'}), 400
        
        # Отменяем задачи
        cancelled = 0
        for job_id in job_ids:
            try:
                job = Job.fetch(job_id, connection=redis_conn)
                if job.get_status() in ['queued', 'started']:
                    job.cancel()
                    cancelled += 1
            except Exception as e:
                logger.warning(f"⚠️ Не удалось отменить задачу {job_id}: {e}")
        
        # Добавляем задачу очистки
        queue.enqueue(cleanup_user_task, user_id, timeout=60)
        
        logger.info(f"⏹️ Остановка публикации для пользователя {user_id}, отменено {cancelled} задач")
        return jsonify({
            'success': True,
            'message': f'Остановлено {cancelled} задач',
            'cancelled': cancelled
        })
        
    except Exception as e:
        logger.error(f"❌ Ошибка остановки: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/webhook', methods=['POST'])
def webhook():
    # Оставляем без изменений
    try:
        data = request.get_json()
        logger.info("📩 ПОЛУЧЕН ВЕБХУК!")
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
        
        logger.info(f"💬 user_id={user_id}, text={text}")
        
        # Создаем API клиент для ответа
        from modules.tasks import _api
        if not _api:
            from modules.tasks import init_globals
            from modules import APIClient
            init_globals(APIClient())
        
        if text and text.strip() == '/start':
            # Отправляем сообщение через API
            url = f"https://platform-api2.max.ru/messages?user_id={user_id}"
            payload = {
                "text": "🏠 **Главное меню**\n\n"
                       "🌐 **Загрузить папку:**\n"
                       f"🔗 https://maxbot.bothost.tech/upload?user_id={user_id}\n\n"
                       "📊 **Получить отчет:**\n"
                       f"🔗 https://maxbot.bothost.tech/report/{user_id}\n\n"
                       "⏹ **Остановить публикацию:** `/stop`\n\n"
                       "📋 **Инструкция:**\n"
                       "1. Подготовьте папки с объявлениями\n"
                       "2. Используйте разделитель #изъятая\n"
                       "3. Фото до 10 шт на объявление\n\n"
                       "⚙️ **Настройки в веб-интерфейсе:**",
                "format": "markdown"
            }
            headers = {"Authorization": TOKEN, "Content-Type": "application/json"}
            requests.post(url, headers=headers, json=payload, timeout=30, verify=False)
            return jsonify({"ok": True}), 200
        
        # ... остальные команды ...
        
        return jsonify({"ok": True}), 200
    except Exception as e:
        logger.error(f"❌ ОШИБКА: {e}")
        return jsonify({"ok": False}), 500

@app.route('/report/<int:user_id>')
def report_page(user_id):
    # Оставляем без изменений
    report_path = report_gen.generate_report(user_id)
    if not report_path:
        return "❌ Нет данных для отчета", 404
    
    filename = os.path.basename(report_path)
    download_url = f"/download_report/{user_id}/{filename}"
    
    return f"""
    <html>
    <head><title>Отчет</title></head>
    <body style="font-family: Arial; max-width: 600px; margin: 50px auto; text-align: center;">
        <h1>📊 Отчет готов!</h1>
        <p><a href="{download_url}" style="display: inline-block; padding: 12px 30px; background: #28a745; color: white; text-decoration: none; border-radius: 5px;">📥 Скачать отчет</a></p>
        <p><a href="/upload">⬅️ Вернуться к загрузке</a></p>
    </body>
    </html>
    """

@app.route('/download_report/<int:user_id>/<path:filename>')
def download_report(user_id, filename):
    # Оставляем без изменений
    try:
        user_folder = fm.get_user_folder(user_id)
        file_path = os.path.join(user_folder, filename)
        
        if not os.path.exists(file_path):
            return "❌ Файл не найден", 404
        
        return send_file(file_path, as_attachment=True, download_name=filename)
    except Exception as e:
        logger.error(f"❌ Ошибка скачивания: {e}")
        return str(e), 500

@app.route('/health')
def health():
    return {"status": "ok"}

@app.route('/status')
def status():
    return {"status": "running", "token_set": bool(TOKEN)}

if __name__ == "__main__":
    # Только для разработки! В production использовать Gunicorn
    port = int(os.environ.get("PORT", 3000))
    if TOKEN:
        logger.info(f"✅ Токен найден (первые 10): {TOKEN[:10]}...")
    app.run(host='0.0.0.0', port=port, debug=False)
