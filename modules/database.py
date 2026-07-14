import sqlite3
import os
import time
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path='/app/data/tokens.db'):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Таблица токенов
        c.execute('''
            CREATE TABLE IF NOT EXISTS user_tokens (
                user_id INTEGER PRIMARY KEY,
                access_token TEXT,
                refresh_token TEXT,
                token_type TEXT,
                expires_at INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица публикаций
        c.execute('''
            CREATE TABLE IF NOT EXISTS publications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                folder_name TEXT NOT NULL,
                group_id TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP,
                error TEXT
            )
        ''')
        
        # Таблица метаданных для отчетов
        c.execute('''
            CREATE TABLE IF NOT EXISTS ad_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                folder_name TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                published_at TIMESTAMP,
                title TEXT,
                source_link TEXT,
                offer_code TEXT,
                price TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("✅ База данных инициализирована")
    
    def add_publication(self, user_id, folder_name, group_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            INSERT INTO publications (user_id, folder_name, group_id, status)
            VALUES (?, ?, ?, ?)
        ''', (user_id, folder_name, group_id, 'pending'))
        conn.commit()
        conn.close()
        logger.info(f"📝 Добавлена публикация: {folder_name} -> {group_id}")
    
    def save_ad_metadata(self, user_id, folder_name, chat_id, metadata, published_at):
        """Сохраняет метаданные для отчета"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            title = metadata.get('Название', '')
            source_link = metadata.get('Ссылка', '')
            offer_code = metadata.get('Код предложения', '')
            price = metadata.get('Цена в лизинге', '')
            
            # Если timestamp - конвертируем в datetime
            if isinstance(published_at, (int, float)):
                published_at = datetime.fromtimestamp(published_at)
            
            c.execute('''
                INSERT INTO ad_metadata 
                (user_id, folder_name, chat_id, published_at, title, source_link, offer_code, price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, folder_name, chat_id, published_at, title, source_link, offer_code, price))
            
            conn.commit()
            conn.close()
            logger.info(f"📊 Метаданные сохранены для {folder_name}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения метаданных: {e}")
            return False
    
    def get_publication_time(self, user_id, folder_name):
        """Возвращает время публикации"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            SELECT published_at FROM ad_metadata 
            WHERE user_id = ? AND folder_name = ?
        ''', (user_id, folder_name))
        row = c.fetchone()
        conn.close()
        if row:
            return datetime.fromisoformat(row[0])
        return None
    
    # ... остальные методы без изменений ...
