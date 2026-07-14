def save_uploaded_files_stream(self, files, user_id, append=False):
    """
    ПОТОКОВОЕ сохранение файлов - НЕ ДЕРЖИТ В ПАМЯТИ!
    Сохраняет файлы чанками по 64KB
    append=True - добавляет файлы в существующую папку
    """
    try:
        user_folder = self.get_user_folder(user_id)
        
        # Если не append - очищаем папку
        if not append:
            if os.path.exists(user_folder):
                shutil.rmtree(user_folder)
            os.makedirs(user_folder, exist_ok=True)
        else:
            # Если append - просто создаем папку, если её нет
            os.makedirs(user_folder, exist_ok=True)
        
        saved_count = 0
        for file in files:
            if not file.filename:
                continue
            
            # Пропускаем системные файлы
            if file.filename.startswith('.'):
                continue
            
            rel_path = file.filename
            full_path = os.path.join(user_folder, rel_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            
            # Сохраняем потоково, чанками по 64KB
            with open(full_path, 'wb') as f:
                while True:
                    chunk = file.stream.read(64 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
            saved_count += 1
        
        logger.info(f"✅ Сохранено {saved_count} файлов потоково (append={append})")
        return {'success': True, 'saved_count': saved_count}
        
    except Exception as e:
        logger.error(f"❌ Ошибка потокового сохранения: {e}")
        return {'success': False, 'error': str(e)}
