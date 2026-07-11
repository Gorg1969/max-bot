def process_zip_stream(self, file, user_id, publisher):
    """Потоковая обработка ZIP-архива с загрузкой фото в MAX"""
    try:
        import zipfile
        import io
        import tempfile
        import re
        
        zip_data = io.BytesIO(file.read())
        published = 0
        errors = []
        bot_token = publisher.api.token
        
        if not bot_token:
            return {'success': False, 'message': 'Токен бота не найден'}
        
        def extract_group_id(folder_name):
            match = re.search(r'-(\d+)', folder_name)
            return match.group(1) if match else None
        
        with zipfile.ZipFile(zip_data, 'r') as zip_ref:
            # Находим все папки с ID групп
            folders = {}
            for name in zip_ref.namelist():
                if name.endswith('/'):
                    folder_name = name.rstrip('/')
                    group_id = extract_group_id(folder_name)
                    if group_id:
                        folders[folder_name] = {
                            'group_id': group_id,
                            'files': []
                        }
                else:
                    for folder in folders:
                        if name.startswith(folder + '/'):
                            folders[folder]['files'].append(name)
                            break
            
            total = len(folders)
            
            for i, (folder_name, data) in enumerate(folders.items(), 1):
                if not publisher.is_running.get(user_id, True):
                    break
                
                # Извлекаем info.txt
                info_content = None
                images = []
                
                for file_name in data['files']:
                    if file_name.lower().endswith(('info.txt', 'info.md')):
                        with zip_ref.open(file_name) as f:
                            info_content = f.read().decode('utf-8', errors='ignore')
                    elif file_name.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
                        images.append(file_name)
                
                if not info_content:
                    errors.append(f"{folder_name}: нет info.txt")
                    continue
                
                # ========== ЗАГРУЖАЕМ ИЗОБРАЖЕНИЯ В MAX ==========
                image_tokens = []
                
                for image_name in images[:10]:
                    try:
                        # Извлекаем изображение из ZIP в память
                        with zip_ref.open(image_name) as f:
                            image_data = f.read()
                        
                        # Создаём временный файл
                        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                            tmp.write(image_data)
                            tmp_path = tmp.name
                        
                        # Загружаем в MAX
                        logger.info(f"📤 Загрузка изображения: {image_name}")
                        token = publisher.upload_image_to_max(tmp_path, bot_token)
                        
                        # Удаляем временный файл
                        os.unlink(tmp_path)
                        
                        if token:
                            image_tokens.append(token)
                            logger.info(f"✅ Изображение загружено: {image_name}")
                        else:
                            logger.warning(f"⚠️ Не удалось загрузить: {image_name}")
                    except Exception as e:
                        logger.error(f"❌ Ошибка загрузки изображения {image_name}: {e}")
                
                # ========== ОТПРАВЛЯЕМ СООБЩЕНИЕ ==========
                if image_tokens:
                    attachments = [{"type": "image", "payload": {"token": t}} for t in image_tokens]
                    result = publisher.api.send_message_to_chat_with_attachments(
                        chat_id=data['group_id'],
                        text=info_content,
                        attachments=attachments
                    )
                    if result:
                        published += 1
                        logger.info(f"✅ Опубликовано: {folder_name}")
                    else:
                        errors.append(f"{folder_name}: ошибка отправки")
                else:
                    # Отправляем только текст
                    result = publisher.api.send_message_to_chat(data['group_id'], info_content)
                    if result:
                        published += 1
                        logger.info(f"✅ Опубликовано (только текст): {folder_name}")
                    else:
                        errors.append(f"{folder_name}: ошибка отправки")
            
        return {'success': True, 'published': published, 'errors': errors}
        
    except Exception as e:
        logger.error(f"❌ Ошибка обработки ZIP: {e}")
        return {'success': False, 'message': str(e)}
