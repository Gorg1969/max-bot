#!/usr/bin/env python3
"""
Диагностическая утилита для проверки бота
Запуск: python test.py
"""

import os
import sys
import platform
import psutil
import time
import requests
import logging

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def check_system():
    """Проверка системных ресурсов"""
    logger.info("=" * 60)
    logger.info("🔍 ДИАГНОСТИКА СИСТЕМЫ")
    logger.info("=" * 60)
    
    # ОС
    logger.info(f"📌 ОС: {platform.system()} {platform.release()}")
    logger.info(f"📌 Python: {sys.version}")
    
    # Память
    mem = psutil.virtual_memory()
    logger.info(f"📌 RAM: {mem.total / (1024**3):.1f} ГБ")
    logger.info(f"📌 Доступно RAM: {mem.available / (1024**3):.1f} ГБ")
    logger.info(f"📌 Использовано RAM: {mem.percent}%")
    
    if mem.percent > 90:
        logger.warning("⚠️ ОЗУ перегружено! Нужно больше памяти или оптимизация.")
    
    # Диск
    disk = psutil.disk_usage('/')
    logger.info(f"📌 Диск: {disk.total / (1024**3):.1f} ГБ")
    logger.info(f"📌 Свободно: {disk.free / (1024**3):.1f} ГБ")
    logger.info(f"📌 Использовано: {disk.percent}%")
    
    if disk.percent > 90:
        logger.warning("⚠️ Диск переполнен! Нужно освободить место.")
    
    # Процессор
    cpu = psutil.cpu_percent(interval=1)
    logger.info(f"📌 CPU: {cpu}%")
    
    if cpu > 90:
        logger.warning("⚠️ CPU перегружен!")
    
    return mem, disk

def check_imports():
    """Проверка импортов модулей"""
    logger.info("=" * 60)
    logger.info("📦 ПРОВЕРКА ИМПОРТОВ")
    logger.info("=" * 60)
    
    modules = [
        'flask',
        'requests',
        'PIL',
        'pandas',
        'numpy',
        'openpyxl',
        'pytz',
        'maxapi'
    ]
    
    for mod in modules:
        try:
            __import__(mod)
            logger.info(f"✅ {mod} - OK")
        except ImportError as e:
            logger.error(f"❌ {mod} - ОШИБКА: {e}")
            return False
    return True

def check_modules():
    """Проверка пользовательских модулей"""
    logger.info("=" * 60)
    logger.info("📁 ПРОВЕРКА МОДУЛЕЙ")
    logger.info("=" * 60)
    
    try:
        from modules import Database, FileManager, Publisher, WebInterface
        logger.info("✅ modules/__init__.py - OK")
    except Exception as e:
        logger.error(f"❌ modules/__init__.py - ОШИБКА: {e}")
        return False
    
    try:
        from modules.database import Database
        logger.info("✅ database.py - OK")
    except Exception as e:
        logger.error(f"❌ database.py - ОШИБКА: {e}")
        return False
    
    try:
        from modules.file_manager import FileManager
        logger.info("✅ file_manager.py - OK")
    except Exception as e:
        logger.error(f"❌ file_manager.py - ОШИБКА: {e}")
        return False
    
    try:
        from modules.publisher import Publisher
        logger.info("✅ publisher.py - OK")
    except Exception as e:
        logger.error(f"❌ publisher.py - ОШИБКА: {e}")
        return False
    
    try:
        from modules.web_interface import WebInterface
        logger.info("✅ web_interface.py - OK")
    except Exception as e:
        logger.error(f"❌ web_interface.py - ОШИБКА: {e}")
        return False
    
    try:
        from modules.max_client import ReportGenerator
        logger.info("✅ max_client.py - OK")
    except Exception as e:
        logger.error(f"❌ max_client.py - ОШИБКА: {e}")
        return False
    
    return True

def check_files():
    """Проверка наличия файлов"""
    logger.info("=" * 60)
    logger.info("📂 ПРОВЕРКА ФАЙЛОВ")
    logger.info("=" * 60)
    
    required_files = [
        'app.py',
        'requirements.txt',
        'modules/__init__.py',
        'modules/database.py',
        'modules/file_manager.py',
        'modules/publisher.py',
        'modules/web_interface.py',
        'modules/max_client.py',
    ]
    
    for file in required_files:
        if os.path.exists(file):
            size = os.path.getsize(file)
            logger.info(f"✅ {file} - OK ({size} байт)")
        else:
            logger.error(f"❌ {file} - НЕ НАЙДЕН!")
            return False
    return True

def check_api():
    """Проверка API MAX"""
    logger.info("=" * 60)
    logger.info("🌐 ПРОВЕРКА API MAX")
    logger.info("=" * 60)
    
    token = os.environ.get('MAX_TOKEN') or os.environ.get('MAX_BOT_TOKEN') or os.environ.get('TOKEN')
    
    if not token:
        logger.error("❌ Токен не найден в переменных окружения!")
        return False
    
    logger.info(f"✅ Токен найден (первые 10): {token[:10]}...")
    
    try:
        url = "https://platform-api2.max.ru/me"
        headers = {"Authorization": token}
        response = requests.get(url, headers=headers, timeout=10, verify=False)
        
        if response.status_code == 200:
            data = response.json()
            logger.info(f"✅ API доступен! Бот: {data.get('first_name', 'Unknown')}")
            return True
        else:
            logger.error(f"❌ Ошибка API: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к API: {e}")
        return False

def check_environment():
    """Проверка переменных окружения"""
    logger.info("=" * 60)
    logger.info("🔧 ПРОВЕРКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ")
    logger.info("=" * 60)
    
    env_vars = [
        'MAX_TOKEN',
        'MAX_BOT_TOKEN',
        'TOKEN',
        'PORT',
        'DATA_DIR',
        'BASE_URL'
    ]
    
    for var in env_vars:
        value = os.environ.get(var)
        if value:
            if 'TOKEN' in var:
                logger.info(f"✅ {var}: {value[:10]}...")
            else:
                logger.info(f"✅ {var}: {value}")
        else:
            logger.info(f"❌ {var}: не установлен")
    
    return True

def quick_test():
    """Быстрый тест - просто проверяет, что бот может запуститься"""
    logger.info("=" * 60)
    logger.info("🚀 БЫСТРЫЙ ТЕСТ ЗАПУСКА")
    logger.info("=" * 60)
    
    try:
        # Пробуем импортировать app
        import app
        logger.info("✅ app.py - импортирован успешно")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка импорта app.py: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Запуск диагностики"""
    logger.info("")
    logger.info("🚀 НАЧАЛО ДИАГНОСТИКИ")
    logger.info("")
    
    results = []
    
    # Проверяем систему
    mem, disk = check_system()
    results.append(("Система", mem.percent < 90))
    
    # Проверяем файлы
    results.append(("Файлы", check_files()))
    
    # Проверяем импорты
    results.append(("Импорты", check_imports()))
    
    # Проверяем модули
    results.append(("Модули", check_modules()))
    
    # Проверяем окружение
    results.append(("Окружение", check_environment()))
    
    # Проверяем API
    results.append(("API", check_api()))
    
    # Быстрый тест
    results.append(("Быстрый тест", quick_test()))
    
    # Итоги
    logger.info("")
    logger.info("=" * 60)
    logger.info("📊 ИТОГИ ДИАГНОСТИКИ")
    logger.info("=" * 60)
    
    all_ok = True
    for name, ok in results:
        status = "✅ OK" if ok else "❌ ОШИБКА"
        logger.info(f"{name}: {status}")
        if not ok:
            all_ok = False
    
    logger.info("=" * 60)
    
    if all_ok:
        logger.info("✅ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ! Бот должен работать.")
        logger.info("💡 Если бот все еще падает - проверьте логи: docker logs")
    else:
        logger.warning("⚠️ ЕСТЬ ОШИБКИ! Исправьте их перед запуском бота.")
    
    logger.info("")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"❌ Критическая ошибка в диагностике: {e}")
        import traceback
        traceback.print_exc()
