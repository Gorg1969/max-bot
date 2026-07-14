# publisher.py
import logging
import os
import time
import re
import json
import threading
import hashlib
from enum import Enum
from PIL import Image, ExifTags
import io

logger = logging.getLogger(__name__)

class UserState(Enum):
    IDLE = "idle"
    PUBLISHING = "publishing"
    STOPPED = "stopped"

class Publisher:
    # Инициализация теперь принимает MaxClient
    def __init__(self, client, file_manager, db):
        self.client = client  # <-- Теперь это MaxClient
        self.fm = file_manager
        self.db = db
        self.user_states = {}
        self.running = False
        self.stop_requested = False
        self.publish_thread = None
        self.published_hashes = set()
        self.hash_file = "published_hashes.json"
        self._load_published_hashes()
        self.global_stop_file = "global_stop.json"
        self._load_global_stop_state()

    def send_message(self, chat_id, text):
        """Отправляет сообщение через MaxClient."""
        if not self.client:
            logger.error("❌ Клиент не инициализирован")
            return False
        return self.client.send_message(chat_id, text)

    # ... все остальные методы остаются без изменений, но используют self.client вместо self.api ...
    # (пропущены для краткости, но они должны быть переписаны для использования self.client)
