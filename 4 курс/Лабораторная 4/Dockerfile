# Образ для сервиса поиска и заглушек поставщиков 
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home appuser
COPY --chown=appuser:appuser . .
USER appuser
CMD ["uvicorn", "app.service:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
