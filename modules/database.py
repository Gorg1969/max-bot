# modules/database.py - Синглтон с WAL для многопользовательской работы

import os
import logging
import sqlite3
from datetime import datetime
import threading
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class Database:
    """Синглтон для работы с SQLite с поддержкой многопользовательского режима"""
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, db_path=None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(Database, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, db_path=None):
        if self._initialized:
            return
        
        self.db_path = db_path or os.environ.get("DATABASE_URL", "/app/data/maxbot.db")
        
        if self.db_path.startswith("postgresql"):
            self.db_path = "/app/data/maxbot.db"
        
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        self._lock = threading.Lock()
        
        # Настройка SQLite для многопользовательской работы
        self._setup_connection_pragmas()
        
        self._init_db()
        self._initialized = True
        logger.info(f"✅ SQLite синглтон инициализирован: {self.db_path}")
    
    def _setup_connection_pragmas(self):
        """Настройка SQLite для многопользовательской работы"""
        with self.get_connection() as conn:
            # WAL режим - позволяет читать и писать одновременно
            conn.execute('PRAGMA journal_mode=WAL')
            # SYNCHRONOUS=NORMAL - баланс скорости и надежности
            conn.execute('PRAGMA synchronous=NORMAL')
            # Увеличиваем кэш для скорости
            conn.execute('PRAGMA cache_size=-20000')  # 20MB
            # Храним временные таблицы в памяти
            conn.execute('PRAGMA temp_store=MEMORY')
            # Включаем поддержку внешних ключей
            conn.execute('PRAGMA foreign_keys=ON')
            # Увеличиваем таймаут для блокировок
            conn.execute('PRAGMA busy_timeout=30000')  # 30 секунд
    
    @contextmanager
    def get_connection(self):
        """Получает соединение с SQLite (контекстный менеджер)"""
        conn = sqlite3.connect(
            self.db_path, 
            timeout=30,
            isolation_level=None,  # Автокоммит для простоты
            check_same_thread=False  # Разрешаем использование из разных потоков
        )
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
                
                # Таблица очереди задач
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
    
    # ========== МЕТОДЫ ДЛЯ РАБОТЫ С ДАННЫМИ ==========
    
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
                logger.info(f"📝 Добавлена публикация: {folder_name} -> {group_id}")
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
                logger.info(f"📊 Метаданные сохранены для {folder_name}")
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
        """Получает список публикаций пользователя"""
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
