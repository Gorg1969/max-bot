@app.route('/publish_folder', methods=['POST'])
def publish_folder():
    try:
        # Получаем данные
        data = request.get_json()
        if not data:
            logger.error("❌ Нет данных в запросе")
            return jsonify({'success': False, 'message': 'Нет данных'}), 400
        
        logger.info(f"📥 Получены данные: {json.dumps(data, ensure_ascii=False)[:500]}")
        
        # Извлекаем user_id
        user_id = data.get('user_id')
        if not user_id:
            logger.error("❌ Нет user_id")
            return jsonify({'success': False, 'message': 'Нет user_id'}), 400
        
        # Извлекаем folder
        folder_data = data.get('folder')
        if not folder_data:
            logger.error("❌ Нет folder_data")
            return jsonify({'success': False, 'message': 'Нет данных папки'}), 400
        
        # Извлекаем max_photos
        max_photos = data.get('max_photos', 6)
        
        # Извлекаем данные папки
        folder_name = folder_data.get('folderName')
        ad_text = folder_data.get('adText')
        metadata_text = folder_data.get('metadataText')
        images = folder_data.get('images', [])
        
        logger.info(f"📦 Получена папка: {folder_name} от пользователя {user_id}")
        logger.info(f"📝 Текст: {len(ad_text) if ad_text else 0} символов")
        logger.info(f"🖼️ Фото: {len(images) if isinstance(images, list) else 0}")
        logger.info(f"📸 Максимум фото: {max_photos}")
        
        if not TOKEN:
            return jsonify({'success': False, 'message': 'Токен не настроен'}), 500
        
        # ПЕРЕДАЕМ max_photos В PUBLISHER
        success, message = publisher.publish_single_folder(
            user_id, 
            folder_name, 
            ad_text, 
            metadata_text, 
            images,
            max_photos  # <-- добавлено
        )
        
        if success:
            return jsonify({'success': True, 'message': message})
        else:
            return jsonify({'success': False, 'message': message}), 500
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500
