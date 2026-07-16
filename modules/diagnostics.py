import os
import sys
import time
import json
import sqlite3
import logging
import psutil
from datetime import datetime
from typing import Dict, Any

logger = logging.getLogger(__name__)

class Diagnostics:
    def __init__(self, db_path='/app/data/tokens.db', data_dir='/app/data'):
        self.db_path = db_path
        self.data_dir = data_dir
        self.start_time = time.time()
    
    def get_system_info(self) -> Dict[str, Any]:
        """Получает информацию о системе"""
        return {
            'version': '2.0.0',
            'python_version': sys.version,
            'uptime_seconds': int(time.time() - self.start_time),
            'uptime_human': self._format_uptime(),
            'memory_usage_mb': round(psutil.Process().memory_info().rss / 1024 / 1024, 2),
            'disk_usage_gb': round(psutil.disk_usage('/').used / 1024 / 1024 / 1024, 2),
        }
    
    def get_database_info(self) -> Dict[str, Any]:
        """Получает информацию о базе данных"""
        try:
            if not os.path.exists(self.db_path):
                return {'status': 'not_found', 'error': 'База данных не найдена'}
            
            size_mb = os.path.getsize(self.db_path) / 1024 / 1024
            
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            tables = {}
            c.execute("SELECT name FROM sqlite_master WHERE type='table'")
            for table in c.fetchall():
                table_name = table[0]
                c.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = c.fetchone()[0]
                tables[table_name] = count
            
            conn.close()
            
            return {
                'status': 'ok',
                'size_mb': round(size_mb, 2),
                'tables': tables,
                'total_records': sum(tables.values())
            }
        except Exception as e:
            return {'status': 'error', 'error': str(e)}
    
    def get_users_stats(self) -> Dict[str, Any]:
        """Получает статистику по пользователям"""
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            
            c.execute("SELECT COUNT(DISTINCT user_id) FROM user_tokens")
            total_users = c.fetchone()[0] or 0
            
            c.execute("""
                SELECT COUNT(DISTINCT user_id) 
                FROM publications 
                WHERE created_at > datetime('now', '-1 day')
            """)
            active_users = c.fetchone()[0] or 0
            
            c.execute("""
                SELECT status, COUNT(*) 
                FROM publications 
                GROUP BY status
            """)
            status_counts = {row[0]: row[1] for row in c.fetchall()}
            
            conn.close()
            
            return {
                'total_users': total_users,
                'active_users_24h': active_users,
                'publications_by_status': status_counts,
                'total_publications': sum(status_counts.values())
            }
        except Exception as e:
            return {'error': str(e)}
    
    def get_recent_logs(self, lines: int = 50) -> str:
        """Получает последние строки логов"""
        log_file = '/app/logs/app.log'
        if not os.path.exists(log_file):
            return "Лог файл не найден"
        
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
                return ''.join(all_lines[-lines:])
        except Exception as e:
            return f"Ошибка чтения логов: {e}"
    
    def get_diagnostics_report(self, include_logs: bool = True) -> Dict[str, Any]:
        """Генерирует полный отчет диагностики"""
        report = {
            'timestamp': datetime.now().isoformat(),
            'system': self.get_system_info(),
            'database': self.get_database_info(),
            'users': self.get_users_stats(),
        }
        
        if include_logs:
            report['recent_logs'] = self.get_recent_logs(30)
        
        return report
    
    def save_report(self, user_id: int = None) -> str:
        """Сохраняет отчет в файл"""
        report = self.get_diagnostics_report(include_logs=True)
        
        if user_id:
            save_dir = os.path.join(self.data_dir, f"user_{user_id}")
        else:
            save_dir = os.path.join(self.data_dir, "diagnostics")
        
        os.makedirs(save_dir, exist_ok=True)
        
        filename = f"diagnostics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(save_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        logger.info(f"📊 Диагностический отчет сохранен: {filepath}")
        return filepath
    
    def _format_uptime(self) -> str:
        """Форматирует время работы"""
        seconds = int(time.time() - self.start_time)
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60
        
        parts = []
        if days > 0:
            parts.append(f"{days}д")
        if hours > 0:
            parts.append(f"{hours}ч")
        if minutes > 0:
            parts.append(f"{minutes}м")
        parts.append(f"{seconds}с")
        
        return " ".join(parts)
