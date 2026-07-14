import requests
import logging

logger = logging.getLogger(__name__)

class MaxClient:
    def __init__(self, token):
        self.token = token
        self.base_url = "https://platform-api2.max.ru"
        self.headers = {
            "Authorization": token,
            "Content-Type": "application/json",
        }

    def _request(self, method, endpoint, params=None, json=None):
        """Базовый метод для отправки синхронных запросов к API."""
        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                params=params,
                json=json,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Ошибка API запроса: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Ответ сервера: {e.response.text}")
            return None

    def get_messages(self, chat_id, count=50):
        """
        Получает последние сообщения из чата (GET /messages).
        Документация: https://dev.max.ru/docs-api/methods/GET/messages
        """
        params = {
            "chat_id": chat_id,
            "count": count,
        }
        logger.debug(f"📥 Запрос сообщений для chat_id={chat_id}")
        result = self._request("GET", "/messages", params=params)
        if result and "messages" in result:
            return result["messages"]
        return []

    def send_message(self, chat_id, text):
        """
        Отправляет сообщение в чат (POST /messages).
        """
        json_data = {
            "recipient": {"chat_id": chat_id},
            "body": {"text": text},
        }
        logger.debug(f"📤 Отправка сообщения в {chat_id}: {text[:50]}...")
        result = self._request("POST", "/messages", json=json_data)
        return result is not None
