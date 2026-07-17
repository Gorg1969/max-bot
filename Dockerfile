FROM python:3.11-slim

WORKDIR /app

# Устанавливаем supervisor и системные пакеты
RUN apt-get update && apt-get install -y \
    gcc \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Копируем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код
COPY . .

# Копируем конфиг supervisor
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Создаем папку для данных
RUN mkdir -p /app/data

ENV PYTHONUNBUFFERED=1
ENV PORT=3000

EXPOSE 3000

# Запускаем supervisor (он запустит gunicorn)
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
