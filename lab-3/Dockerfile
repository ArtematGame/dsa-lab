FROM python:3.12-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim AS runtime

RUN groupadd -r appgroup && useradd -r -g appgroup -d /app -s /sbin/nologin appuser

WORKDIR /app
COPY --from=builder /install /usr/local
COPY meeting_room_ddd.py booking_process.py adapters.py app.py ./

ENV PORT=8000 \
    LOG_LEVEL=INFO \
    PYTHONUNBUFFERED=1

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import os, urllib.request; port=os.environ.get('PORT','8000'); urllib.request.urlopen(f'http://127.0.0.1:{port}/health')" || exit 1

CMD ["sh", "-c", "gunicorn -w 1 -b 0.0.0.0:${PORT:-8000} --log-level $(echo ${LOG_LEVEL:-info} | tr '[:upper:]' '[:lower:]') app:app"]
