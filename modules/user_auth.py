import os
import json
import logging
import requests
from flask import request, redirect, url_for
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

class UserAuth:
    """Проверка пользователей и авторизация через Google OAuth"""
    
    def __init__(self, db, client_id=None, client_secret=None, redirect_uri=None):
        self.db = db  # ← Просто сохраняем db, не импортируем его
        self.client_id = client_id or os.environ.get("GOOGLE_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("GOOGLE_CLIENT_SECRET")
        self.redirect_uri = redirect_uri or os.environ.get("OAUTH_REDIRECT_URI", "https://maxbot.bothost.tech/oauth2callback")
        self.auth_url = "https://accounts.google.com/o/oauth2/auth"
        self.token_url = "https://oauth2.googleapis.com/token"
        self.scope = "https://www.googleapis.com/auth/drive.file"
    
    def get_authorization_url(self, user_id):
        """Генерация ссылки для авторизации в Google"""
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": self.scope,
            "access_type": "offline",
            "state": str(user_id),
            "prompt": "consent"
        }
        return f"{self.auth_url}?{urlencode(params)}"
    
    def handle_oauth_callback(self, code, state):
        """Обработка callback от Google после авторизации"""
        try:
            data = {
                "code": code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri,
                "grant_type": "authorization_code"
            }
            response = requests.post(self.token_url, data=data, timeout=30)
            
            if response.status_code != 200:
                logger.error(f"❌ Ошибка получения токена: {response.text}")
                return None
            
            token_data = response.json()
            user_id = int(state) if state else None
            
            if user_id:
                self.db.save_user_token(
                    user_id=user_id,
                    access_token=token_data.get("access_token"),
                    refresh_token=token_data.get("refresh_token"),
                    expires_in=token_data.get("expires_in"),
                    token_type=token_data.get("token_type")
                )
                logger.info(f"✅ Пользователь {user_id} успешно авторизован")
                return token_data
            
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка OAuth callback: {e}")
            return None
    
    def refresh_token_if_needed(self, user_id):
        """Обновление токена, если он истёк"""
        token_data = self.db.get_user_token(user_id)
        if not token_data:
            return None
        
        import time
        if token_data.get("expires_at", 0) < time.time():
            logger.info(f"🔄 Токен для {user_id} истёк, обновляем...")
            data = {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": token_data.get("refresh_token"),
                "grant_type": "refresh_token"
            }
            try:
                response = requests.post(self.token_url, data=data, timeout=30)
                if response.status_code == 200:
                    new_token = response.json()
                    self.db.save_user_token(
                        user_id=user_id,
                        access_token=new_token.get("access_token"),
                        refresh_token=token_data.get("refresh_token"),
                        expires_in=new_token.get("expires_in")
                    )
                    logger.info(f"✅ Токен для {user_id} обновлён")
                    return new_token.get("access_token")
                else:
                    logger.error(f"❌ Ошибка обновления токена: {response.text}")
                    return None
            except Exception as e:
                logger.error(f"❌ Ошибка обновления токена: {e}")
                return None
        
        return token_data.get("access_token")
    
    def get_user_token(self, user_id):
        """Получение валидного токена для пользователя"""
        return self.refresh_token_if_needed(user_id)
