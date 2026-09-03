# Стадия 1: Установка зависимостей
FROM python:3.11-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Стадия 2: Финальный образ
FROM python:3.11-slim

WORKDIR /app

# Копируем установленные зависимости из первой стадии
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Копируем код приложения
COPY . .

# Запуск через gunicorn
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:5000"]