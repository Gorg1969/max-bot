FROM python:3.11-slim

WORKDIR /app

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    python3-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Очищаем BOM и невидимые символы из requirements.txt
RUN sed -i 's/^\xEF\xBB\xBF//' requirements.txt 2>/dev/null || true && \
    sed -i 's/^\xFF\xFE//' requirements.txt 2>/dev/null || true && \
    sed -i 's/^\xFE\xFF//' requirements.txt 2>/dev/null || true && \
    tr -d '\r\0' < requirements.txt > requirements.txt.tmp && mv requirements.txt.tmp requirements.txt 2>/dev/null || true

RUN cat requirements.txt && echo '--- Requirements.txt содержимое выше ---'

RUN set -e && \
    echo 'Начинаем установку зависимостей из requirements.txt...' && \
    if [ ! -f requirements.txt ] || [ ! -s requirements.txt ]; then \
        echo 'WARNING: requirements.txt пуст или не существует'; \
    else \
        while IFS= read -r line || [ -n "$line" ]; do \
            [ -z "$line" ] && continue; \
            line=$(echo "$line" | sed 's/^\xEF\xBB\xBF//' | sed 's/^\xFF\xFE//' | sed 's/^\xFE\xFF//' | tr -d '\r\0' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'); \
            [ -z "$line" ] && continue; \
            case "$line" in \
              \#*) continue ;; \
            esac; \
            echo "=== Устанавливаем: $line ===" && \
            if echo "$line" | grep -qiE '^(sqlite3|json|os|sys|time|datetime|re|random|math|logging|asyncio|collections|itertools|functools|operator|pathlib|urllib|http|socket|ssl|hashlib|base64|uuid|threading|multiprocessing|queue|concurrent|subprocess|shutil|tempfile|pickle|copy|weakref|gc|ctypes|struct|array|binascii|codecs|encodings|locale|gettext|argparse|configparser|csv|io|textwrap|string|unicodedata|readline|rlcompleter)$'; then \
                echo "ℹ️  Пропускаем встроенный модуль Python: $line (не требует установки)"; \
                continue; \
            fi && \
            if echo "$line" | grep -qiE '(python-dotenv|tgcrypto).*=='; then \
                if ! pip install --no-cache-dir "$line"; then \
                    echo "WARNING: Не удалось установить $line (возможно несуществующая версия)"; \
                    pkg_name=$(echo "$line" | sed 's/[<>=!].*//' | xargs); \
                    echo "Пробуем установить $pkg_name без версии..."; \
                    pip install --no-cache-dir "$pkg_name" || echo "WARNING: Не удалось установить $pkg_name даже без версии"; \
                else \
                    echo "✅ Успешно установлен: $line"; \
                fi; \
            else \
                if ! pip install --no-cache-dir "$line"; then \
                    echo "ERROR: Не удалось установить $line" && exit 1; \
                else \
                    echo "✅ Успешно установлен: $line"; \
                fi; \
            fi; \
        done < requirements.txt; \
    fi && \
    echo 'Установка завершена' && \
    echo '=== Проверка установленных пакетов ===' && \
    (pip list 2>/dev/null | grep -E '(aiogram|dotenv|telegram|requests|supabase)' || echo 'WARNING: Некоторые модули не найдены') && \
    echo '=== Проверка python-dotenv ===' && \
    (pip show python-dotenv >/dev/null 2>&1 && echo '✅ python-dotenv установлен' || echo '❌ python-dotenv НЕ установлен')

RUN pip cache purge || true

COPY . .

ENV DATA_DIR=/app/data
RUN mkdir -p /app/data && chmod 777 /app/data
RUN chown -R $(id -u):$(id -g) /app/data 2>/dev/null || chown -R 1000:1000 /app/data || true

# 🔥 ДОБАВЛЯЕМ ЭТУ СТРОКУ:
EXPOSE 3000

CMD ["python", "app.py"]