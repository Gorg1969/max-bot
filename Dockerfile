FROM python:3.11-slim

WORKDIR /app

# Копируем зависимости и устанавливаем
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем ВЕСЬ код
COPY . .

# Открываем порт
EXPOSE 3000

# Запускаем бота
CMD ["python", "app.py"]
