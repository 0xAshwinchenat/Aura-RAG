# Use a clean, official Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

# Set work directory
WORKDIR /app

# Install system dependencies (including Tesseract OCR for image ingestion)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    tesseract-ocr \
    libtesseract-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Install reportlab for test file generation
RUN pip install --no-cache-dir reportlab==4.1.0

# Copy project files
COPY . .

# Expose server port
EXPOSE 8000

# Start server launcher
CMD ["python", "run.py", "--serve", "--host", "0.0.0.0", "--port", "8000"]
