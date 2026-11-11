# Установка зависимостей в отдельной стадии сборки.
FROM python:3.11-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Компактный образ для фонового обработчика.
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
# Запуск Worker от непривилегированного пользователя.
RUN useradd --create-home --uid 1000 appuser
WORKDIR /app
COPY --from=builder /install /usr/local
COPY --chown=appuser:appuser domain.py db.py main.py ./
USER appuser
# Запуск обработчика очереди.
CMD ["python", "main.py"]
