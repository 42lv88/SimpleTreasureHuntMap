FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (tesseract for offline OCR)
RUN apt-get update && \
    apt-get install -y tesseract-ocr && \
    rm -rf /var/lib/apt/lists/*

# Install python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code (excludes __pycache__ via .dockerignore)
COPY main.py .

EXPOSE 8000

# Render sets $PORT — uvicorn must bind to it
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
