# modules/database.py - SQLite версия с оптимизацией

import os
import logging
import sqlite3
from datetime import datetime
import json
import threading
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path=None):
        """Инициализация SQLite с поддержкой многопоточности"""
        self.db_path = db_path or os.environ.get(
            "DATABASE_URL", 
            "/app/data/maxbot.db"
        )
        
        # Если DATABASE_URL начинается с postgresql, используем SQLite
        if self.db_path.startswith("postgresql"):
            self.db_path = "/app/data/maxbot.db"
        
        # Создаем директорию для БД
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        # Локальная блокировка для потокобезопасности
        self._lock = threading.Lock()
        
        self._init_db()
        logger.info(f"✅ Подключение к SQLite: {self.db_path}")
    
    @contextmanager
    def get_connection(self):
        """Получает соединение с SQLite (контекстный менеджер)"""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def _init_db(self):
        """Инициализация таблиц в SQLite"""
        with self.get_connection() as conn:
            try:
                cur = conn.cursor()
                
                # Включаем поддержку внешних ключей
                cur.execute('PRAGMA foreign_keys = ON')
                
                # Таблица пользователей
                cur.execute('''
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
                cur.execute('''
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
                
                # Индексы для быстрого поиска
                cur.execute('''
                    CREATE INDEX IF NOT EXISTS idx_publications_user_id 
                    ON publications(user_id)
                ''')
                
                cur.execute('''
                    CREATE INDEX IF NOT EXISTS idx_publications_created_at 
                    ON publications(created_at DESC)
                ''')
                
                cur.execute('''
                    CREATE INDEX IF NOT EXISTS idx_publications_status 
                    ON publications(status)
                ''')
                
                # Таблица метаданных
                cur.execute('''
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
                
                # Индексы для метаданных
                cur.execute('''
                    CREATE INDEX IF NOT EXISTS idx_ad_metadata_user_id 
                    ON ad_metadata(user_id)
                ''')
                
                cur.execute('''
                    CREATE INDEX IF NOT EXISTS idx_ad_metadata_folder_name 
                    ON ad_metadata(folder_name)
                ''')
                
                cur.execute('''
                    CREATE INDEX IF NOT EXISTS idx_ad_metadata_user_folder 
                    ON ad_metadata(user_id, folder_name)
                ''')
                
                # Таблица очереди задач (для асинхронной обработки)
                cur.execute('''
                    CREATE TABLE IF NOT EXISTS task_queue (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        folder_name TEXT NOT NULL,
                        status TEXT DEFAULT 'pending',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        started_at TIMESTAMP,
                        completed_at TIMESTAMP,
                        error TEXT,
                        result TEXT
                    )
                ''')
                
                cur.execute('''
                    CREATE INDEX IF NOT EXISTS idx_task_queue_user_status 
                    ON task_queue(user_id, status)
                ''')
                
                conn.commit()
                logger.info("✅ Таблицы SQLite инициализированы")
                
            except Exception as e:
                logger.error(f"❌ Ошибка инициализации SQLite: {e}")
                conn.rollback()
                raise
    
    def add_publication(self, user_id, folder_name, group_id, post_id=None):
        """Добавляет запись о публикации"""
        with self.get_connection() as conn:
            try:
                cur = conn.cursor()
                cur.execute('''
                    INSERT INTO publications (user_id, folder_name, group_id, post_id, status)
                    VALUES (?, ?, ?, ?, ?)
                ''', (user_id, folder_name, group_id, post_id, 'success'))
                
                pub_id = cur.lastrowid
                conn.commit()
                logger.info(f"📝 Добавлена публикация: {folder_name} -> {group_id}, post_id={post_id}")
                return pub_id
            except Exception as e:
                logger.error(f"❌ Ошибка добавления публикации: {e}")
                conn.rollback()
                raise
    
    def save_ad_metadata(self, user_id, folder_name, chat_id, metadata, published_at, post_id=None, post_link=None):
        """Сохраняет метаданные для отчета"""
        with self.get_connection() as conn:
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
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (user_id, folder_name, chat_id, post_id, post_link, 
                      published_at, title, source_link, offer_code, price))
                
                conn.commit()
                logger.info(f"📊 Метаданные сохранены для {folder_name}, post_link={post_link}")
                return True
                
            except Exception as e:
                logger.error(f"❌ Ошибка сохранения метаданных: {e}")
                conn.rollback()
                return False
    
    def get_ad_metadata(self, user_id, folder_name):
        """Получает метаданные из БД"""
        with self.get_connection() as conn:
            try:
                cur = conn.cursor()
                cur.execute('''
                    SELECT title, source_link, offer_code, price, post_link, post_id
                    FROM ad_metadata 
                    WHERE user_id = ? AND folder_name = ?
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
    
    def get_publications(self, user_id, limit=None, status=None):
        """Получает список публикаций пользователя с фильтрацией"""
        with self.get_connection() as conn:
            try:
                cur = conn.cursor()
                query = '''
                    SELECT folder_name, group_id, post_id, status, created_at 
                    FROM publications 
                    WHERE user_id = ?
                '''
                params = [user_id]
                
                if status:
                    query += ' AND status = ?'
                    params.append(status)
                
                query += ' ORDER BY created_at ASC'
                
                if limit:
                    query += f" LIMIT {limit}"
                
                cur.execute(query, params)
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
    
    def get_user_publications_count(self, user_id):
        """Получает количество публикаций пользователя"""
        with self.get_connection() as conn:
            try:
                cur = conn.cursor()
                cur.execute('''
                    SELECT COUNT(*) as count 
                    FROM publications 
                    WHERE user_id = ?
                ''', (user_id,))
                
                row = cur.fetchone()
                return row['count'] if row else 0
            except Exception as e:
                logger.error(f"❌ Ошибка подсчета публикаций: {e}")
                return 0
    
    def get_all_users(self):
        """Получает список всех пользователей"""
        with self.get_connection() as conn:
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
    
    def get_user_stats(self, user_id):
        """Получает статистику пользователя"""
        with self.get_connection() as conn:
            try:
                cur = conn.cursor()
                cur.execute('''
                    SELECT 
                        COUNT(*) as total,
                        SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                        SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as errors
                    FROM publications 
                    WHERE user_id = ?
                ''', (user_id,))
                
                row = cur.fetchone()
                if row:
                    return {
                        'total': row['total'] or 0,
                        'success': row['success'] or 0,
                        'errors': row['errors'] or 0
                    }
                return {'total': 0, 'success': 0, 'errors': 0}
            except Exception as e:
                logger.error(f"❌ Ошибка получения статистики: {e}")
                return {'total': 0, 'success': 0, 'errors': 0}
    
    def add_task(self, user_id, folder_name):
        """Добавляет задачу в очередь"""
        with self.get_connection() as conn:
            try:
                cur = conn.cursor()
                cur.execute('''
                    INSERT INTO task_queue (user_id, folder_name, status)
                    VALUES (?, ?, 'pending')
                ''', (user_id, folder_name))
                
                task_id = cur.lastrowid
                conn.commit()
                return task_id
            except Exception as e:
                logger.error(f"❌ Ошибка добавления задачи: {e}")
                conn.rollback()
                return None
    
    def update_task_status(self, task_id, status, error=None, result=None):
        """Обновляет статус задачи"""
        with self.get_connection() as conn:
            try:
                cur = conn.cursor()
                now = datetime.now()
                
                if status == 'started':
                    cur.execute('''
                        UPDATE task_queue 
                        SET status = ?, started_at = ?
                        WHERE id = ?
                    ''', (status, now, task_id))
                elif status == 'completed' or status == 'error':
                    cur.execute('''
                        UPDATE task_queue 
                        SET status = ?, completed_at = ?, error = ?, result = ?
                        WHERE id = ?
                    ''', (status, now, error, result, task_id))
                else:
                    cur.execute('''
                        UPDATE task_queue 
                        SET status = ?
                        WHERE id = ?
                    ''', (status, task_id))
                
                conn.commit()
                return True
            except Exception as e:
                logger.error(f"❌ Ошибка обновления задачи: {e}")
                conn.rollback()
                return False
    
    def get_pending_tasks(self, user_id=None, limit=10):
        """Получает ожидающие задачи"""
        with self.get_connection() as conn:
            try:
                cur = conn.cursor()
                query = '''
                    SELECT id, user_id, folder_name, status, created_at
                    FROM task_queue 
                    WHERE status = 'pending'
                '''
                params = []
                
                if user_id:
                    query += ' AND user_id = ?'
                    params.append(user_id)
                
                query += ' ORDER BY created_at ASC LIMIT ?'
                params.append(limit)
                
                cur.execute(query, params)
                rows = cur.fetchall()
                
                tasks = []
                for row in rows:
                    tasks.append({
                        'id': row['id'],
                        'user_id': row['user_id'],
                        'folder_name': row['folder_name'],
                        'status': row['status'],
                        'created_at': row['created_at']
                    })
                return tasks
            except Exception as e:
                logger.error(f"❌ Ошибка получения задач: {e}")
                return []
    
    def close(self):
        """Закрывает все соединения"""
        logger.info("🔒 Соединения с SQLite закрыты")
