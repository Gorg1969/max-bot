class APIClient:
    def send_message(self, user_id, text):
        try:
            payload = {"text": text, "format": "markdown"}
            response = requests.post(
                f"{BASE_URL}/messages",
                headers={"Authorization": TOKEN, "Content-Type": "application/json"},
                params={"user_id": user_id},
                json=payload,
                timeout=30,
                verify=False
            )
            if response.status_code == 200:
                return True
            else:
                logger.error(f"❌ Ошибка отправки: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logger.error(f"❌ Ошибка отправки: {e}")
            return False
    
    # НОВАЯ ФУНКЦИЯ: отправка в группу (чат)
    def send_message_to_chat(self, chat_id, text):
        try:
            payload = {"text": text, "format": "markdown"}
            response = requests.post(
                f"{BASE_URL}/messages",
                headers={"Authorization": TOKEN, "Content-Type": "application/json"},
                params={"chat_id": chat_id},
                json=payload,
                timeout=30,
                verify=False
            )
            if response.status_code == 200:
                return True
            else:
                logger.error(f"❌ Ошибка отправки в чат: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logger.error(f"❌ Ошибка отправки в чат: {e}")
            return False
