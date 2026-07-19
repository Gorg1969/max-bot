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
        self.migrate_db()
    
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
                post_link TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("✅ База данных инициализирована")
    
    def migrate_db(self):
        """Обновляет структуру БД при необходимости"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            # Проверяем наличие колонки post_link в ad_metadata
            c.execute("PRAGMA table_info(ad_metadata)")
            columns = [col[1] for col in c.fetchall()]
            
            if 'post_link' not in columns:
                c.execute('ALTER TABLE ad_metadata ADD COLUMN post_link TEXT')
                logger.info("✅ Добавлена колонка post_link в ad_metadata")
            
            # Проверяем наличие колонки error в publications
            c.execute("PRAGMA table_info(publications)")
            columns = [col[1] for col in c.fetchall()]
            
            if 'error' not in columns:
                c.execute('ALTER TABLE publications ADD COLUMN error TEXT')
                logger.info("✅ Добавлена колонка error в publications")
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"❌ Ошибка миграции БД: {e}")
    
    def add_publication(self, user_id, folder_name, group_id, status='pending', error=None):
        """Добавляет запись о публикации"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            INSERT INTO publications (user_id, folder_name, group_id, status, error, created_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (user_id, folder_name, group_id, status, error))
        
        conn.commit()
        conn.close()
        logger.info(f"📝 Добавлена публикация: {folder_name} -> {group_id} (статус: {status})")
    
    def update_publication_status(self, user_id, folder_name, status, error=None):
        """Обновляет статус публикации"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''
                UPDATE publications 
                SET status = ?, error = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND folder_name = ?
            ''', (status, error, user_id, folder_name))
            conn.commit()
            conn.close()
            logger.info(f"📝 Обновлен статус {folder_name}: {status}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка обновления статуса: {e}")
            return False
    
    def save_ad_metadata(self, user_id, folder_name, chat_id, metadata, published_at):
        """Сохраняет метаданные для отчета"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            title = metadata.get('Название', '')
            source_link = metadata.get('Ссылка', '')
            offer_code = metadata.get('Код предложения', '')
            price = metadata.get('Цена в лизинге', '')
            post_link = metadata.get('post_link', '')
            
            # Преобразуем timestamp в datetime
            if isinstance(published_at, (int, float)):
                published_at = datetime.fromtimestamp(published_at)
            
            c.execute('''
                INSERT INTO ad_metadata 
                (user_id, folder_name, chat_id, published_at, title, source_link, offer_code, price, post_link)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, folder_name, chat_id, published_at, title, source_link, offer_code, price, post_link))
            
            conn.commit()
            conn.close()
            logger.info(f"📊 Метаданные сохранены для {folder_name}, post_link: {post_link}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения метаданных: {e}")
            return False
    
    def update_post_link(self, user_id, folder_name, post_link):
        """Обновляет ссылку на пост в ad_metadata"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''
                UPDATE ad_metadata 
                SET post_link = ?
                WHERE user_id = ? AND folder_name = ?
                ORDER BY id DESC LIMIT 1
            ''', (post_link, user_id, folder_name))
            conn.commit()
            conn.close()
            logger.info(f"🔗 Обновлена ссылка для {folder_name}: {post_link}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка обновления ссылки: {e}")
            return False
    
    def get_post_link(self, user_id, folder_name):
        """Получает post_link для папки"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''
                SELECT post_link FROM ad_metadata 
                WHERE user_id = ? AND folder_name = ?
                ORDER BY id DESC LIMIT 1
            ''', (user_id, folder_name))
            row = c.fetchone()
            conn.close()
            return row[0] if row and row[0] else None
        except Exception as e:
            logger.error(f"❌ Ошибка получения post_link: {e}")
            return None
    
    def get_ad_metadata(self, user_id, folder_name):
        """Получает метаданные из БД"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''
                SELECT title, source_link, offer_code, price, post_link 
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
                    'post_link': row[4] or ''
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
                SELECT folder_name, group_id, status, created_at, error 
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
                    'status': row[2],
                    'created_at': row[3],
                    'error': row[4] if len(row) > 4 else None
                })
            return publications
        except Exception as e:
            logger.error(f"❌ Ошибка получения публикаций: {e}")
            return []
    
    def get_publication_time(self, user_id, folder_name):
        """Получает время публикации для папки"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute('''
                SELECT created_at 
                FROM publications 
                WHERE user_id = ? AND folder_name = ? AND status = 'success'
                ORDER BY id DESC LIMIT 1
            ''', (user_id, folder_name))
            row = c.fetchone()
            conn.close()
            
            if row and row[0]:
                if isinstance(row[0], str):
                    return datetime.fromisoformat(row[0])
                return row[0]
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка получения времени публикации: {e}")
            return None
    
    def get_published_at(self, user_id, folder_name):
        """Получает время публикации из ad_metadata"""
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
                return row[0]
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка получения published_at: {e}")
            return None
    
    def clear_user_data(self, user_id):
        """Полностью очищает все данные пользователя из БД"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            c.execute('DELETE FROM publications WHERE user_id = ?', (user_id,))
            c.execute('DELETE FROM ad_metadata WHERE user_id = ?', (user_id,))
            
            conn.commit()
            conn.close()
            
            logger.info(f"🗑️ Все данные пользователя {user_id} удалены из БД")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка очистки данных пользователя: {e}")
            return False
    
    def get_stats(self, user_id):
        """Получает статистику публикаций пользователя"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            c.execute('SELECT COUNT(*) FROM publications WHERE user_id = ?', (user_id,))
            total = c.fetchone()[0]
            
            c.execute('SELECT COUNT(*) FROM publications WHERE user_id = ? AND status = "success"', (user_id,))
            success = c.fetchone()[0]
            
            c.execute('SELECT COUNT(*) FROM publications WHERE user_id = ? AND status != "success"', (user_id,))
            errors = c.fetchone()[0]
            
            conn.close()
            
            return {
                'total': total,
                'success': success,
                'errors': errors
            }
        except Exception as e:
            logger.error(f"❌ Ошибка получения статистики: {e}")
            return {'total': 0, 'success': 0, 'errors': 0}
    
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
                c.execute('''
                    UPDATE ad_metadata 
                    SET published_at = CURRENT_TIMESTAMP 
                    WHERE user_id = ? AND published_at IS NULL
                ''', (user_id,))
            else:
                c.execute('''
                    UPDATE publications 
                    SET created_at = CURRENT_TIMESTAMP 
                    WHERE created_at IS NULL
                ''')
                c.execute('''
                    UPDATE ad_metadata 
                    SET published_at = CURRENT_TIMESTAMP 
                    WHERE published_at IS NULL
                ''')
            
            conn.commit()
            conn.close()
            logger.info("✅ Время публикаций исправлено")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка исправления времени: {e}")
            return False
