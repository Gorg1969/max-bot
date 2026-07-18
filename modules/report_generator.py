# modules/database.py - добавьте метод для исправления времени

def fix_publication_times(self, user_id=None):
    """Исправляет время публикации для старых записей"""
    try:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        if user_id:
            c.execute('''
                UPDATE publications 
                SET created_at = CURRENT_TIMESTAMP 
                WHERE user_id = ? AND created_at IS NULL
            ''', (user_id,))
        else:
            c.execute('''
                UPDATE publications 
                SET created_at = CURRENT_TIMESTAMP 
                WHERE created_at IS NULL
            ''')
        
        conn.commit()
        conn.close()
        logger.info("✅ Время публикаций исправлено")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка исправления времени: {e}")
        return False
