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
        conn.commit()
        conn.close()
    
    # ========== МЕТОДЫ ДЛЯ ТОКЕНОВ ==========
    
    def save_user_token(self, user_id, access_token, refresh_token=None, expires_in=None, token_type='Bearer'):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        if expires_in:
            if isinstance(expires_in, timedelta):
                expires_at = int(time.time() + expires_in.total_seconds())
            elif isinstance(expires_in, datetime):
                expires_at = int(expires_in.timestamp())
            elif isinstance(expires_in, (int, float)):
                expires_at = int(time.time() + expires_in)
            else:
                expires_at = int(time.time() + 3600)
        else:
            expires_at = None
        
        c.execute('''
            INSERT OR REPLACE INTO user_tokens 
            (user_id, access_token, refresh_token, token_type, expires_at, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (user_id, access_token, refresh_token, token_type, expires_at))
        conn.commit()
        conn.close()
        logger.info(f"✅ Токен сохранён для пользователя {user_id}")
    
    def get_user_token(self, user_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            'SELECT access_token, refresh_token, token_type, expires_at FROM user_tokens WHERE user_id = ?',
            (user_id,)
        )
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
    
    def delete_user_token(self, user_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('DELETE FROM user_tokens WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        logger.info(f"🗑️ Токен удалён для пользователя {user_id}")
    
    # ========== МЕТОДЫ ДЛЯ ПУБЛИКАЦИЙ ==========
    
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
    
    def update_publication_status(self, folder_name, status, error=None):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        if error:
            c.execute('''
                UPDATE publications 
                SET status = ?, updated_at = CURRENT_TIMESTAMP, error = ? 
                WHERE folder_name = ?
            ''', (status, error, folder_name))
        else:
            c.execute('''
                UPDATE publications 
                SET status = ?, updated_at = CURRENT_TIMESTAMP 
                WHERE folder_name = ?
            ''', (status, folder_name))
        conn.commit()
        conn.close()
    
    def get_pending_publications(self, user_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            SELECT folder_name, group_id FROM publications 
            WHERE user_id = ? AND status = 'pending'
        ''', (user_id,))
        rows = c.fetchall()
        conn.close()
        return rows
    
    def clear_user_publications(self, user_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('DELETE FROM publications WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
