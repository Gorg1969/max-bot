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
                    if isinstance(row[0], str):
                        return datetime.fromisoformat(row[0])
                    return row[0]
                except:
                    return datetime.now()
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка получения времени публикации: {e}")
            return None
    
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
    
    def update_publication_status(self, user_id, folder_name, status, error=None):
        """Обновляет статус публикации"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''
                UPDATE publications 
                SET status = ?, updated_at = CURRENT_TIMESTAMP, error = ?
                WHERE user_id = ? AND folder_name = ?
            ''', (status, error, user_id, folder_name))
            conn.commit()
            conn.close()
            logger.info(f"📝 Статус публикации обновлен: {folder_name} -> {status}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка обновления статуса: {e}")
            return False
    
    def get_user_token(self, user_id):
        """Получает токен пользователя"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''
                SELECT access_token, refresh_token, token_type, expires_at 
                FROM user_tokens 
                WHERE user_id = ?
            ''', (user_id,))
            row = c.fetchone()
            conn.close()
            
            if row:
                return {
                    'access_token': row[0],
                    'refresh_token': row[1],
                    'token_type': row[2],
                    'expires_at': row[3]
                }
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка получения токена: {e}")
            return None
    
    def save_user_token(self, user_id, access_token, refresh_token=None, token_type='Bearer', expires_at=None):
        """Сохраняет токен пользователя"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''
                INSERT OR REPLACE INTO user_tokens 
                (user_id, access_token, refresh_token, token_type, expires_at, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ''', (user_id, access_token, refresh_token, token_type, expires_at))
            conn.commit()
            conn.close()
            logger.info(f"✅ Токен сохранен для пользователя {user_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения токена: {e}")
            return False
    
    def clear_user_data(self, user_id):
        """Очищает все данные пользователя из БД"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('DELETE FROM publications WHERE user_id = ?', (user_id,))
            c.execute('DELETE FROM ad_metadata WHERE user_id = ?', (user_id,))
            c.execute('DELETE FROM user_tokens WHERE user_id = ?', (user_id,))
            conn.commit()
            conn.close()
            logger.info(f"🗑️ Данные пользователя {user_id} очищены из БД")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка очистки данных: {e}")
            return False
    
    def get_stats(self, user_id):
        """Получает статистику по публикациям"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            # Всего публикаций
            c.execute('SELECT COUNT(*) FROM publications WHERE user_id = ?', (user_id,))
            total = c.fetchone()[0]
            
            # Успешных
            c.execute('SELECT COUNT(*) FROM publications WHERE user_id = ? AND status = "success"', (user_id,))
            success = c.fetchone()[0]
            
            # Ошибок
            c.execute('SELECT COUNT(*) FROM publications WHERE user_id = ? AND status = "error"', (user_id,))
            error = c.fetchone()[0]
            
            conn.close()
            
            return {
                'total': total,
                'success': success,
                'error': error,
                'pending': total - success - error
            }
        except Exception as e:
            logger.error(f"❌ Ошибка получения статистики: {e}")
            return {'total': 0, 'success': 0, 'error': 0, 'pending': 0}
