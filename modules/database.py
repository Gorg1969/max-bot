# modules/database.py - PostgreSQL версия

import os
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import SimpleConnectionPool
from datetime import datetime
import time

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_url=None):
        """Инициализация подключения к PostgreSQL"""
        self.db_url = db_url or os.environ.get(
            "DATABASE_URL", 
            "postgresql://postgres:postgres@postgres:5432/maxbot"
        )
        self.pool = None
        self._init_pool()
        self._init_db()
    
    def _init_pool(self):
        """Создает пул подключений к PostgreSQL"""
        try:
            self.pool = SimpleConnectionPool(
                minconn=1,
                maxconn=10,
                dsn=self.db_url,
                cursor_factory=RealDictCursor
            )
            logger.info(f"✅ Подключение к PostgreSQL: {self.db_url}")
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к PostgreSQL: {e}")
            raise
    
    def get_connection(self):
        """Получает соединение из пула"""
        if not self.pool:
            self._init_pool()
        return self.pool.getconn()
    
    def return_connection(self, conn):
        """Возвращает соединение в пул"""
        if self.pool and conn:
            self.pool.putconn(conn)
    
    def _init_db(self):
        """Инициализация таблиц в PostgreSQL"""
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            
            # Таблица пользователей
            cur.execute('''
                CREATE TABLE IF NOT EXISTS user_tokens (
                    user_id BIGINT PRIMARY KEY,
                    access_token TEXT,
                    refresh_token TEXT,
                    token_type TEXT,
                    expires_at BIGINT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица публикаций
            cur.execute('''
                CREATE TABLE IF NOT EXISTS publications (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    folder_name TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    post_id TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP,
                    error TEXT
                )
            ''')
            
            # Индексы для быстрого поиска
            cur.execute('''
                CREATE INDEX IF NOT EXISTS idx_publications_user_id 
                ON publications(user_id)
            ''')
            
            cur.execute('''
                CREATE INDEX IF NOT EXISTS idx_publications_created_at 
                ON publications(created_at DESC)
            ''')
            
            # Таблица метаданных
            cur.execute('''
                CREATE TABLE IF NOT EXISTS ad_metadata (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
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
            
            # Индексы для метаданных
            cur.execute('''
                CREATE INDEX IF NOT EXISTS idx_ad_metadata_user_id 
                ON ad_metadata(user_id)
            ''')
            
            cur.execute('''
                CREATE INDEX IF NOT EXISTS idx_ad_metadata_folder_name 
                ON ad_metadata(folder_name)
            ''')
            
            conn.commit()
            logger.info("✅ Таблицы PostgreSQL инициализированы")
            
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации PostgreSQL: {e}")
            conn.rollback()
            raise
        finally:
            cur.close()
            self.return_connection(conn)
    
    def add_publication(self, user_id, folder_name, group_id, post_id=None):
        """Добавляет запись о публикации"""
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute('''
                INSERT INTO publications (user_id, folder_name, group_id, post_id, status)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            ''', (user_id, folder_name, group_id, post_id, 'success'))
            
            pub_id = cur.fetchone()['id']
            conn.commit()
            logger.info(f"📝 Добавлена публикация: {folder_name} -> {group_id}, post_id={post_id}")
            return pub_id
        except Exception as e:
            logger.error(f"❌ Ошибка добавления публикации: {e}")
            conn.rollback()
            raise
        finally:
            cur.close()
            self.return_connection(conn)
    
    def save_ad_metadata(self, user_id, folder_name, chat_id, metadata, published_at, post_id=None, post_link=None):
        """Сохраняет метаданные для отчета"""
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            
            title = metadata.get('Название', '')
            source_link = metadata.get('Ссылка', '')
            offer_code = metadata.get('Код предложения', '')
            price = metadata.get('Цена в лизинге', '')
            
            if isinstance(published_at, (int, float)):
                published_at = datetime.fromtimestamp(published_at)
            
            cur.execute('''
                INSERT INTO ad_metadata 
                (user_id, folder_name, chat_id, post_id, post_link, 
                 published_at, title, source_link, offer_code, price)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (user_id, folder_name, chat_id, post_id, post_link, 
                  published_at, title, source_link, offer_code, price))
            
            conn.commit()
            logger.info(f"📊 Метаданные сохранены для {folder_name}, post_link={post_link}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения метаданных: {e}")
            conn.rollback()
            return False
        finally:
            cur.close()
            self.return_connection(conn)
    
    def get_ad_metadata(self, user_id, folder_name):
        """Получает метаданные из БД"""
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute('''
                SELECT title, source_link, offer_code, price, post_link, post_id
                FROM ad_metadata 
                WHERE user_id = %s AND folder_name = %s
                ORDER BY id DESC LIMIT 1
            ''', (user_id, folder_name))
            
            row = cur.fetchone()
            
            if row:
                return {
                    'Название': row['title'] or '',
                    'Ссылка': row['source_link'] or '',
                    'Код предложения': row['offer_code'] or '',
                    'Цена в лизинге': row['price'] or '',
                    'post_link': row['post_link'] or '',
                    'post_id': row['post_id'] or ''
                }
            return {}
        except Exception as e:
            logger.error(f"❌ Ошибка получения метаданных: {e}")
            return {}
        finally:
            cur.close()
            self.return_connection(conn)
    
    def get_publications(self, user_id, limit=None):
        """Получает список публикаций пользователя"""
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            query = '''
                SELECT folder_name, group_id, post_id, status, created_at 
                FROM publications 
                WHERE user_id = %s
                ORDER BY created_at ASC
            '''
            if limit:
                query += f" LIMIT {limit}"
            
            cur.execute(query, (user_id,))
            rows = cur.fetchall()
            
            publications = []
            for row in rows:
                publications.append({
                    'folder_name': row['folder_name'],
                    'group_id': row['group_id'],
                    'post_id': row['post_id'],
                    'status': row['status'],
                    'created_at': row['created_at']
                })
            return publications
        except Exception as e:
            logger.error(f"❌ Ошибка получения публикаций: {e}")
            return []
        finally:
            cur.close()
            self.return_connection(conn)
    
    def get_user_publications_count(self, user_id):
        """Получает количество публикаций пользователя"""
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute('''
                SELECT COUNT(*) as count 
                FROM publications 
                WHERE user_id = %s
            ''', (user_id,))
            
            row = cur.fetchone()
            return row['count'] if row else 0
        except Exception as e:
            logger.error(f"❌ Ошибка подсчета публикаций: {e}")
            return 0
        finally:
            cur.close()
            self.return_connection(conn)
    
    def get_all_users(self):
        """Получает список всех пользователей"""
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute('''
                SELECT DISTINCT user_id 
                FROM publications 
                ORDER BY user_id
            ''')
            
            rows = cur.fetchall()
            return [row['user_id'] for row in rows]
        except Exception as e:
            logger.error(f"❌ Ошибка получения списка пользователей: {e}")
            return []
        finally:
            cur.close()
            self.return_connection(conn)
    
    def close(self):
        """Закрывает все соединения"""
        if self.pool:
            self.pool.closeall()
            logger.info("🔒 Соединения с PostgreSQL закрыты")
