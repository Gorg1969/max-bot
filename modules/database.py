import sqlite3
import os
import time
import logging

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path='/app/data/tokens.db'):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
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
        conn.commit()
        conn.close()
    
    def save_user_token(self, user_id, access_token, refresh_token=None, expires_in=None, token_type='Bearer'):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        # ✅ ИСПРАВЛЕННАЯ СТРОКА:
        expires_at = int(time.time() + expires_in) if expires_in else None
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
