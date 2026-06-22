FROM python:3.11-slim

# System deps for Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo zlib1g libwebp7 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Persistent dirs (data + uploads). На Timeweb Cloud примонтируй сюда volume.
RUN mkdir -p /app/data /app/static/uploads
VOLUME ["/app/data", "/app/static/uploads"]

ENV PORT=8000
ENV PYTHONUNBUFFERED=1
ENV DATA_DIR=/app/data
ENV UPLOAD_DIR=/app/static/uploads

EXPOSE 8000

# Gunicorn для продакшна: 2 воркера, длинный таймаут для бэкапов
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "--timeout", "120", "app:app"]
