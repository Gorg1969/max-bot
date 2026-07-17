# modules/session_manager.py
import uuid
import threading
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class SessionManager:
    def __init__(self, session_timeout: int = 300):
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.user_sessions: Dict[int, str] = {}
        self.SESSION_TIMEOUT = session_timeout
        self._lock = threading.Lock()
        self._running = True
        
        # Запускаем очистку в фоне
        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()
        logger.info("✅ SessionManager инициализирован")
    
    def create_session(self, user_id: int, context: Dict = None) -> str:
        """Создает новую сессию"""
        with self._lock:
            session_id = str(uuid.uuid4())
            
            # Закрываем старую сессию
            if user_id in self.user_sessions:
                old_session = self.user_sessions[user_id]
                if old_session in self.sessions:
                    self._close_session_internal(old_session)
            
            session_data = {
                'user_id': user_id,
                'created_at': datetime.now(),
                'last_activity': datetime.now(),
                'context': context or {},
                'state': 'idle',
                'message_queue': [],
                'current_action': None,
                'data': {}  # Хранилище для данных сессии
            }
            
            self.sessions[session_id] = session_data
            self.user_sessions[user_id] = session_id
            
            logger.info(f"🆕 Создана сессия {session_id[:8]} для пользователя {user_id}")
            return session_id
    
    def get_session(self, session_id: str) -> Optional[Dict]:
        """Получает сессию по ID"""
        with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                return None
            
            # Проверка на истечение
            if datetime.now() - session['last_activity'] > timedelta(seconds=self.SESSION_TIMEOUT):
                self._close_session_internal(session_id)
                return None
            
            session['last_activity'] = datetime.now()
            return session
    
    def get_session_by_user(self, user_id: int) -> Optional[Dict]:
        """Получает сессию по ID пользователя"""
        with self._lock:
            session_id = self.user_sessions.get(user_id)
            if not session_id:
                return None
            return self.get_session(session_id)
    
    def add_message(self, session_id: str, message: str) -> bool:
        """Добавляет сообщение в очередь"""
        with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                return False
            
            session['message_queue'].append({
                'timestamp': datetime.now(),
                'message': message
            })
            session['last_activity'] = datetime.now()
            return True
    
    def get_next_message(self, session_id: str) -> Optional[str]:
        """Получает следующее сообщение из очереди"""
        with self._lock:
            session = self.sessions.get(session_id)
            if not session or not session['message_queue']:
                return None
            
            return session['message_queue'].pop(0)['message']
    
    def set_state(self, session_id: str, state: str) -> bool:
        """Устанавливает состояние сессии"""
        with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                return False
            
            session['state'] = state
            session['last_activity'] = datetime.now()
            return True
    
    def get_state(self, session_id: str) -> Optional[str]:
        """Получает состояние сессии"""
        session = self.get_session(session_id)
        if not session:
            return None
        return session.get('state', 'idle')
    
    def set_data(self, session_id: str, key: str, value: Any) -> bool:
        """Сохраняет данные в сессии"""
        with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                return False
            
            session['data'][key] = value
            session['last_activity'] = datetime.now()
            return True
    
    def get_data(self, session_id: str, key: str, default: Any = None) -> Any:
        """Получает данные из сессии"""
        session = self.get_session(session_id)
        if not session:
            return default
        
        return session['data'].get(key, default)
    
    def close_session(self, session_id: str) -> Optional[Dict]:
        """Закрывает сессию"""
        with self._lock:
            return self._close_session_internal(session_id)
    
    def _close_session_internal(self, session_id: str) -> Optional[Dict]:
        """Внутренний метод закрытия сессии"""
        session = self.sessions.pop(session_id, None)
        if session:
            user_id = session['user_id']
            if self.user_sessions.get(user_id) == session_id:
                del self.user_sessions[user_id]
            logger.info(f"🧹 Сессия {session_id[:8]} для пользователя {user_id} закрыта")
        return session
    
    def _cleanup_loop(self):
        """Фоновый процесс очистки сессий"""
        while self._running:
            time.sleep(60)  # Проверка каждую минуту
            try:
                self._cleanup_expired()
            except Exception as e:
                logger.error(f"❌ Ошибка очистки сессий: {e}")
    
    def _cleanup_expired(self):
        """Очищает истекшие сессии"""
        with self._lock:
            current_time = datetime.now()
            expired = []
            
            for session_id, session in self.sessions.items():
                if current_time - session['last_activity'] > timedelta(seconds=self.SESSION_TIMEOUT):
                    expired.append(session_id)
            
            for session_id in expired:
                self._close_session_internal(session_id)
            
            if expired:
                logger.info(f"🧹 Удалено {len(expired)} истекших сессий")
    
    def stop(self):
        """Останавливает менеджер"""
        self._running = False
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=5)
