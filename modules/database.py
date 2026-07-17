# modules/database.py

import sqlite3
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path='/app/data/tokens.db'):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Инициализация базы данных и миграция при первом запуске"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # Таблица пользователей
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
                post_id TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP,
                error TEXT
            )
        ''')
        
        # Проверяем и добавляем колонку post_id если её нет
        try:
            c.execute("SELECT post_id FROM publications LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE publications ADD COLUMN post_id TEXT")
            logger.info("✅ Добавлена колонка post_id в publications")
        
        # Таблица метаданных для отчетов
        c.execute('''
            CREATE TABLE IF NOT EXISTS ad_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                folder_name TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                post_id TEXT,
                post_link TEXT,
                published_at TIMESTAMP,
                title TEXT,
                source_link TEXT,
                offer_code TEXT,
                price TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Проверяем и добавляем колонку post_id если её нет
        try:
            c.execute("SELECT post_id FROM ad_metadata LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE ad_metadata ADD COLUMN post_id TEXT")
            logger.info("✅ Добавлена колонка post_id в ad_metadata")
        
        # Проверяем и добавляем колонку post_link если её нет
        try:
            c.execute("SELECT post_link FROM ad_metadata LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE ad_metadata ADD COLUMN post_link TEXT")
            logger.info("✅ Добавлена колонка post_link в ad_metadata")
        
        conn.commit()
        conn.close()
        logger.info("✅ База данных инициализирована и проверена")
    
    def add_publication(self, user_id, folder_name, group_id, post_id=None):
        """Добавляет запись о публикации"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            INSERT INTO publications (user_id, folder_name, group_id, post_id, status)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, folder_name, group_id, post_id, 'success'))
        conn.commit()
        conn.close()
        logger.info(f"📝 Добавлена публикация: {folder_name} -> {group_id}, post_id={post_id}")
    
    def save_ad_metadata(self, user_id, folder_name, chat_id, metadata, published_at, post_id=None, post_link=None):
        """Сохраняет метаданные для отчета с post_id и post_link"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            title = metadata.get('Название', '')
            source_link = metadata.get('Ссылка', '')
            offer_code = metadata.get('Код предложения', '')
            price = metadata.get('Цена в лизинге', '')
            
            if isinstance(published_at, (int, float)):
                published_at = datetime.fromtimestamp(published_at)
            
            c.execute('''
                INSERT INTO ad_metadata 
                (user_id, folder_name, chat_id, post_id, post_link, published_at, title, source_link, offer_code, price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, folder_name, chat_id, post_id, post_link, published_at, title, source_link, offer_code, price))
            
            conn.commit()
            conn.close()
            logger.info(f"📊 Метаданные сохранены для {folder_name}, post_link={post_link}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения метаданных: {e}")
            return False
    
    def get_ad_metadata(self, user_id, folder_name):
        """Получает метаданные из БД"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''
                SELECT title, source_link, offer_code, price, post_link, post_id
                FROM ad_metadata 
                WHERE user_id = ? AND folder_name = ?
                ORDER BY id DESC LIMIT 1
            ''', (user_id, folder_name))
            row = c.fetchone()
            conn.close()
            
            if row:
                return {
                    'Название': row[0] or '',
                    'Ссылка': row[1] or '',
                    'Код предложения': row[2] or '',
                    'Цена в лизинге': row[3] or '',
                    'post_link': row[4] or '',
                    'post_id': row[5] or ''
                }
            return {}
        except Exception as e:
            logger.error(f"❌ Ошибка получения метаданных: {e}")
            return {}
    
    def get_publications(self, user_id, limit=None):
        """Получает список публикаций пользователя в порядке создания (старые -> новые)"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            query = '''
                SELECT folder_name, group_id, post_id, status, created_at 
                FROM publications 
                WHERE user_id = ?
                ORDER BY created_at ASC
            '''
            if limit:
                query += f" LIMIT {limit}"
            
            c.execute(query, (user_id,))
            rows = c.fetchall()
            conn.close()
            
            publications = []
            for row in rows:
                publications.append({
                    'folder_name': row[0],
                    'group_id': row[1],
                    'post_id': row[2],
                    'status': row[3],
                    'created_at': row[4]
                })
            return publications
        except Exception as e:
            logger.error(f"❌ Ошибка получения публикаций: {e}")
            return []
