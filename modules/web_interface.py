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
