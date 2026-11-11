# Установка библиотек в отдельной стадии сборки.
FROM python:3.11-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Компактный образ для запуска API.
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
# Запуск приложения от непривилегированного пользователя.
RUN useradd --create-home --uid 1000 appuser
WORKDIR /app
COPY --from=builder /install /usr/local
COPY --chown=appuser:appuser schemas.py tables.py main.py ./
USER appuser
# Порт HTTP API.
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
