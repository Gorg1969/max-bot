FROM python:3.9-slim

WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    curl \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Копирование зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода
COPY . .

# Создание папки для данных
RUN mkdir -p /app/data

# Открываем порт
EXPOSE 3000

# ✅ Запуск через Gunicorn (НЕ через Flask!)
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]
