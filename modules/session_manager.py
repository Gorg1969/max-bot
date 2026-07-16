import requests
import threading
import time
import logging
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)

class SessionManager:
    """
    Управляет сессиями пользователей.
    Каждый пользователь имеет свою независимую сессию.
    """
    
    def __init__(self, token: str, base_url: str):
        self.token = token
        self.base_url = base_url
        self.sessions: Dict[int, requests.Session] = {}
        self.locks: Dict[int, threading.Lock] = {}
        self.last_send_time: Dict[int, float] = {}
        self.min_interval = 3  # минимальный интервал между сообщениями ОДНОГО пользователя
        
    def get_session(self, user_id: int) -> requests.Session:
        """Получает или создает сессию для пользователя"""
        if user_id not in self.sessions:
            session = requests.Session()
            session.headers.update({
                'Authorization': self.token,
                'Content-Type': 'application/json'
            })
            session.verify = False
            self.sessions[user_id] = session
            self.locks[user_id] = threading.Lock()
            self.last_send_time[user_id] = 0
            logger.info(f"🔐 Создана новая сессия для пользователя {user_id}")
        
        return self.sessions[user_id]
    
    def send_message(self, user_id: int, chat_id: str = None, text: str = "", 
                    attachments: list = None, is_user: bool = False) -> tuple[bool, Optional[str]]:
        """
        Отправляет сообщение от имени пользователя.
        Возвращает (успех, message_id)
        """
        with self.locks.get(user_id, threading.Lock()):
            session = self.get_session(user_id)
            
            # Проверяем интервал между сообщениями ОТ ЭТОГО пользователя
            elapsed = time.time() - self.last_send_time.get(user_id, 0)
            if elapsed < self.min_interval:
                wait_time = self.min_interval - elapsed
                logger.info(f"⏳ Пользователь {user_id} ждет {wait_time:.1f}с (интервал)")
                time.sleep(wait_time)
            
            # Формируем запрос
            payload = {"text": text, "format": "markdown"}
            if attachments:
                payload["attachments"] = attachments
            
            try:
                # Формируем URL и параметры
                if is_user:
                    # Личное сообщение
                    url = f"{self.base_url}/messages"
                    params = {"user_id": user_id}
                else:
                    # Чат
                    url = f"{self.base_url}/messages"
                    params = {"chat_id": chat_id}
                
                response = session.post(
                    url,
                    params=params,
                    json=payload,
                    timeout=60
                )
                
                self.last_send_time[user_id] = time.time()
                
                if response.status_code == 200:
                    result = response.json()
                    message_id = result.get('id') or result.get('message_id')
                    logger.info(f"✅ Сообщение от пользователя {user_id} отправлено")
                    return True, message_id
                else:
                    logger.error(f"❌ Ошибка: {response.status_code} - {response.text[:200]}")
                    return False, None
                    
            except Exception as e:
                logger.error(f"❌ Ошибка отправки для {user_id}: {e}")
                return False, None
    
    def cleanup_user(self, user_id: int):
        """Очищает сессию пользователя"""
        if user_id in self.sessions:
            self.sessions[user_id].close()
            del self.sessions[user_id]
        if user_id in self.locks:
            del self.locks[user_id]
        if user_id in self.last_send_time:
            del self.last_send_time[user_id]
        logger.info(f"🧹 Сессия пользователя {user_id} очищена")
