@app.route('/publish_error', methods=['POST'])
def publish_error():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        folder_name = data.get('folder_name')
        error = data.get('error', 'Неизвестная ошибка')
        
        if not user_id or not folder_name:
            return jsonify({'success': False, 'message': 'Нет данных'}), 400
        
        # Извлекаем chat_id из имени папки
        chat_id = publisher.extract_chat_id_from_folder(folder_name)
        if not chat_id:
            chat_id = 'unknown'
        
        # Добавляем запись в БД со статусом error
        db.add_publication(user_id, folder_name, chat_id, status='error', error=error)
        
        logger.info(f"❌ Записана ошибка для {folder_name}: {error}")
        
        # Проверяем, не завершены ли все публикации
        pending_count = db.count_pending_publications(user_id)
        
        if pending_count == 0:
            # Запускаем генерацию отчета в фоне
            def send_report_after_error():
                time.sleep(3)
                try:
                    from modules.report_generator import ReportGenerator
                    report_gen = ReportGenerator(fm, db)
                    report_path = report_gen.generate_report(user_id)
                    
                    if report_path:
                        filename = os.path.basename(report_path)
                        download_url = f"https://maxbot.bothost.tech/download_report/{user_id}/{filename}"
                        stats = db.get_stats(user_id)
                        
                        api.send_message(
                            user_id,
                            f"📊 **Отчет готов!**\n\n"
                            f"✅ Процесс завершен\n"
                            f"📦 Всего: {stats.get('total', 0)}\n"
                            f"✅ Успешно: {stats.get('success', 0)}\n"
                            f"❌ Ошибок: {stats.get('errors', 0)}\n\n"
                            f"🔗 [Скачать отчет]({download_url})\n\n"
                            f"📋 Отчет также доступен по ссылке:\n"
                            f"https://maxbot.bothost.tech/status_page/{user_id}"
                        )
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки отчета после ошибки: {e}")
            
            threading.Thread(target=send_report_after_error, daemon=True).start()
        
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"❌ Ошибка записи ошибки: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500
