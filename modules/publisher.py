# app.py - добавить эндпоинт

@app.route('/diagnostic/<int:user_id>')
def diagnostic_log(user_id):
    """Показывает диагностический журнал для пользователя"""
    try:
        # Проверяем, что пользователь существует
        user_folder = fm.get_user_folder(user_id)
        if not os.path.exists(user_folder):
            return jsonify({'error': 'Пользователь не найден'}), 404
        
        # Получаем диагностический журнал из publisher
        diagnostic_data = publisher.get_diagnostic_log()
        
        # Фильтруем по user_id если есть в данных
        user_diagnostic = []
        for entry in diagnostic_data:
            # Если в записи есть user_id, проверяем
            if entry.get('user_id') == user_id:
                user_diagnostic.append(entry)
            # Или если в записи есть chat_id, проверяем через БД
            elif entry.get('chat_id'):
                # Проверяем, принадлежит ли chat_id этому пользователю
                publications = db.get_publications(user_id)
                for pub in publications:
                    if pub.get('group_id') == entry.get('chat_id'):
                        user_diagnostic.append(entry)
                        break
        
        # Если нет отфильтрованных, показываем все последние
        if not user_diagnostic:
            user_diagnostic = diagnostic_data[-20:]  # Последние 20 записей
        
        return jsonify({
            'user_id': user_id,
            'total_entries': len(diagnostic_data),
            'user_entries': len(user_diagnostic),
            'diagnostic': user_diagnostic[-50:]  # Последние 50 записей
        })
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения диагностики: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/diagnostic/clear', methods=['POST'])
def clear_diagnostic_log():
    """Очищает диагностический журнал"""
    try:
        publisher.clear_diagnostic_log()
        return jsonify({'success': True, 'message': 'Диагностический журнал очищен'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500
