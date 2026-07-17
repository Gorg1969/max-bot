# migrate_to_postgres.py - миграция данных

import sqlite3
import psycopg2
import os
from psycopg2.extras import RealDictCursor

SQLITE_DB = "/app/data/tokens.db"
POSTGRES_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@postgres:5432/maxbot")

def migrate():
    print("🔄 Начинаем миграцию с SQLite на PostgreSQL...")
    
    # Подключение к SQLite
    sqlite_conn = sqlite3.connect(SQLITE_DB)
    sqlite_conn.row_factory = sqlite3.Row
    sqlite_cursor = sqlite_conn.cursor()
    
    # Подключение к PostgreSQL
    pg_conn = psycopg2.connect(POSTGRES_URL)
    pg_cursor = pg_conn.cursor()
    
    try:
        # Миграция user_tokens
        print("📦 Миграция user_tokens...")
        sqlite_cursor.execute("SELECT * FROM user_tokens")
        rows = sqlite_cursor.fetchall()
        for row in rows:
            pg_cursor.execute("""
                INSERT INTO user_tokens (user_id, access_token, refresh_token, token_type, expires_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    access_token = EXCLUDED.access_token,
                    refresh_token = EXCLUDED.refresh_token,
                    token_type = EXCLUDED.token_type,
                    expires_at = EXCLUDED.expires_at,
                    updated_at = EXCLUDED.updated_at
            """, (row['user_id'], row['access_token'], row['refresh_token'], 
                  row['token_type'], row['expires_at'], row['updated_at']))
        print(f"  ✅ {len(rows)} записей")

        # Миграция publications
        print("📦 Миграция publications...")
        sqlite_cursor.execute("SELECT * FROM publications")
        rows = sqlite_cursor.fetchall()
        for row in rows:
            pg_cursor.execute("""
                INSERT INTO publications (id, user_id, folder_name, group_id, post_id, status, created_at, updated_at, error)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    folder_name = EXCLUDED.folder_name,
                    group_id = EXCLUDED.group_id,
                    post_id = EXCLUDED.post_id,
                    status = EXCLUDED.status,
                    updated_at = EXCLUDED.updated_at,
                    error = EXCLUDED.error
            """, (row['id'], row['user_id'], row['folder_name'], row['group_id'],
                  row['post_id'], row['status'], row['created_at'], row['updated_at'], row['error']))
        print(f"  ✅ {len(rows)} записей")

        # Миграция ad_metadata
        print("📦 Миграция ad_metadata...")
        sqlite_cursor.execute("SELECT * FROM ad_metadata")
        rows = sqlite_cursor.fetchall()
        for row in rows:
            pg_cursor.execute("""
                INSERT INTO ad_metadata (id, user_id, folder_name, chat_id, post_id, post_link, 
                                         published_at, title, source_link, offer_code, price, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    folder_name = EXCLUDED.folder_name,
                    chat_id = EXCLUDED.chat_id,
                    post_id = EXCLUDED.post_id,
                    post_link = EXCLUDED.post_link,
                    published_at = EXCLUDED.published_at,
                    title = EXCLUDED.title,
                    source_link = EXCLUDED.source_link,
                    offer_code = EXCLUDED.offer_code,
                    price = EXCLUDED.price
            """, (row['id'], row['user_id'], row['folder_name'], row['chat_id'],
                  row['post_id'], row['post_link'], row['published_at'],
                  row['title'], row['source_link'], row['offer_code'], 
                  row['price'], row['created_at']))
        print(f"  ✅ {len(rows)} записей")

        pg_conn.commit()
        print("✅ Миграция успешно завершена!")

    except Exception as e:
        print(f"❌ Ошибка миграции: {e}")
        pg_conn.rollback()
    finally:
        sqlite_conn.close()
        pg_conn.close()

if __name__ == "__main__":
    migrate()
