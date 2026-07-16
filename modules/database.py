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
        
        # Таблица публикаций с новыми полями
        c.execute('''
            CREATE TABLE IF NOT EXISTS publications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                folder_name TEXT NOT NULL,
                group_id TEXT NOT NULL,
                message_id TEXT,
                full_url TEXT,
                status TEXT DEFAULT 'pending',
                error_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP,
                error TEXT
            )
        ''')
        
        # Добавляем новые колонки если их нет
        try:
            c.execute('ALTER TABLE publications ADD COLUMN message_id TEXT')
        except sqlite3.OperationalError:
            pass
        
        try:
            c.execute('ALTER TABLE publications ADD COLUMN full_url TEXT')
        except sqlite3.OperationalError:
            pass
        
        try:
            c.execute('ALTER TABLE publications ADD COLUMN error_text TEXT')
        except sqlite3.OperationalError:
            pass
        
        # Таблица метаданных
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
    
    def add_publication(self, user_id, folder_name, group_id, message_id=None, full_url=None):
        """Добавляет запись о публикации с полной ссылкой"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            INSERT INTO publications (user_id, folder_name, group_id, message_id, full_url, status)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, folder_name, group_id, message_id, full_url, 'success'))
        conn.commit()
        conn.close()
        logger.info(f"📝 Добавлена публикация: {folder_name} -> {group_id}")
    
    def add_publication_error(self, user_id, folder_name, group_id, error_text):
        """Добавляет запись об ошибке публикации"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            INSERT INTO publications (user_id, folder_name, group_id, status, error_text)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, folder_name, group_id, 'error', error_text))
        conn.commit()
        conn.close()
        logger.warning(f"⚠️ Ошибка публикации {folder_name}: {error_text}")
    
    def save_ad_metadata(self, user_id, folder_name, chat_id, metadata, published_at):
        """Сохраняет метаданные для отчета"""
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
    
    def get_ad_metadata(self, user_id, folder_name):
        """Получает метаданные из БД"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''
                SELECT title, source_link, offer_code, price 
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
                    'Цена в лизинге': row[3] or ''
                }
            return {}
        except Exception as e:
            logger.error(f"❌ Ошибка получения метаданных: {e}")
            return {}
    
    def get_publications(self, user_id, limit=None):
        """Получает список публикаций пользователя"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            query = '''
                SELECT folder_name, group_id, status, created_at 
                FROM publications 
                WHERE user_id = ?
                ORDER BY created_at DESC
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
                    'status': row[2],
                    'created_at': row[3]
                })
            return publications
        except Exception as e:
            logger.error(f"❌ Ошибка получения публикаций: {e}")
            return []
    
    def get_publications_with_status(self, user_id, status=None):
        """Получает публикации с фильтром по статусу"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            query = '''
                SELECT folder_name, group_id, message_id, full_url, status, error_text, created_at 
                FROM publications 
                WHERE user_id = ?
            '''
            params = [user_id]
            
            if status:
                query += " AND status = ?"
                params.append(status)
            
            query += " ORDER BY created_at DESC"
            
            c.execute(query, params)
            rows = c.fetchall()
            conn.close()
            
            publications = []
            for row in rows:
                publications.append({
                    'folder_name': row[0],
                    'group_id': row[1],
                    'message_id': row[2],
                    'full_url': row[3],
                    'status': row[4],
                    'error_text': row[5],
                    'created_at': row[6]
                })
            return publications
        except Exception as e:
            logger.error(f"❌ Ошибка получения публикаций: {e}")
            return []
