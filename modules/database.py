# Добавьте эти методы в класс Database

def get_publication_time(self, user_id, folder_name):
    """Возвращает время публикации из БД"""
    try:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            SELECT published_at FROM ad_metadata 
            WHERE user_id = ? AND folder_name = ?
            ORDER BY id DESC LIMIT 1
        ''', (user_id, folder_name))
        row = c.fetchone()
        conn.close()
        
        if row and row[0]:
            # Если это timestamp
            if isinstance(row[0], (int, float)):
                return datetime.fromtimestamp(row[0])
            # Если это строка
            try:
                return datetime.fromisoformat(row[0])
            except:
                return datetime.now()
        return None
    except Exception as e:
        logger.error(f"❌ Ошибка получения времени публикации: {e}")
        return None
