#!/usr/bin/env python3
"""
Настройка вебхука для MAX Bot на Render.com
🔒 БЕЗОПАСНАЯ ВЕРСИЯ - токен берется из переменных окружения
"""
import os
import requests
import sys
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== КОНФИГ =====
# ✅ ТОКЕН ТОЛЬКО ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ!
TOKEN = os.environ.get("TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://max-bot-ulzl.onrender.com/webhook")
BASE_URL = "https://platform-api2.max.ru"

def setup_webhook():
    """Настройка вебхука с токеном из окружения"""
    
    if not TOKEN:
        logger.error("❌ ТОКЕН НЕ НАЙДЕН!")
        logger.error("👉 Установите переменную TOKEN в Environment Variables на Render")
        return False
    
    token_preview = f"{TOKEN[:4]}...{TOKEN[-4:]}" if len(TOKEN) > 8 else "***"
    logger.info(f"🔑 Токен: {token_preview}")
    logger.info(f"🌐 Вебхук: {WEBHOOK_URL}")
    
    # ✅ ИСПРАВЛЕНО: ТОЛЬКО ТОКЕН, БЕЗ "Bearer "
    headers = {
        "Authorization": TOKEN,  # <-- ИСПРАВЛЕНО!
        "Content-Type": "application/json"
    }
    
    # 1. Удаляем старую подписку
    logger.info("🗑️ Удаление старой подписки...")
    try:
        r_del = requests.delete(
            f"{BASE_URL}/subscriptions",
            headers=headers,
            timeout=10,
            verify=False
        )
        logger.info(f"   Статус: {r_del.status_code}")
        if r_del.status_code == 200:
            logger.info("   ✅ Старая подписка удалена")
    except Exception as e:
        logger.warning(f"   ⚠️ Ошибка: {e}")
    
    # 2. Создаем новую подписку
    logger.info("📝 Создание новой подписки...")
    try:
        payload = {"url": WEBHOOK_URL}
        r = requests.post(
            f"{BASE_URL}/subscriptions",
            headers=headers,
            json=payload,
            timeout=10,
            verify=False
        )
        logger.info(f"   Статус: {r.status_code}")
        
        if r.status_code == 200:
            logger.info("🎉 ВЕБХУК УСПЕШНО НАСТРОЕН!")
            logger.info(f"   ✅ Вебхук: {WEBHOOK_URL}")
            return True
        else:
            logger.error(f"❌ Ошибка: {r.text[:200]}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Ошибка подключения: {e}")
        return False

def main():
    """Главная функция"""
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print("""
Использование:
  python setup_render.py

Переменные окружения:
  TOKEN         - Токен бота (обязательно)
  WEBHOOK_URL   - URL вебхука (по умолчанию: https://max-bot-ulzl.onrender.com/webhook)
        """)
        return
    
    success = setup_webhook()
    
    if success:
        logger.info("\n📊 Проверка вебхука...")
        try:
            r = requests.get(WEBHOOK_URL, timeout=5, verify=False)
            logger.info(f"   🌐 Вебхук доступен: {r.status_code}")
        except:
            logger.warning("   ⚠️ Вебхук не отвечает (может быть нормой)")
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
