import sqlite3
import os

class Database:
    def __init__(self, db_path='/app/data/publications.db'):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
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
    
    def add_publication(self, user_id, folder_name, group_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            'INSERT INTO publications (user_id, folder_name, group_id, status) VALUES (?, ?, ?, ?)',
            (user_id, folder_name, group_id, 'pending')
        )
        conn.commit()
        conn.close()
    
    def update_status(self, folder_name, status, error=None):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        if error:
            c.execute(
                'UPDATE publications SET status = ?, updated_at = CURRENT_TIMESTAMP, error = ? WHERE folder_name = ?',
                (status, error, folder_name)
            )
        else:
            c.execute(
                'UPDATE publications SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE folder_name = ?',
                (status, folder_name)
            )
        conn.commit()
        conn.close()
    
    def delete_user_data(self, user_id):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('DELETE FROM publications WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
