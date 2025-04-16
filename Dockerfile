# Use Python 3.11 slim as base image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    libfuzzy-dev \
    libssl-dev \
    pkg-config \
    libmagic1 \
    curl \
    ca-certificates \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements.txt first for better layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /app/data/uploads && \
    mkdir -p /app/data/database && \
    mkdir -p /app/static/css && \
    mkdir -p /app/static/js && \
    mkdir -p /app/templates && \
    chmod -R 755 /app/data

# Set environment variables for runtime
ENV DATABASE_PATH=/app/data/malware_platform.db \
    UPLOAD_FOLDER=/app/data/uploads \
    MAX_UPLOAD_SIZE_MB=100 \
    PORT=8080

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1

# Run the application with gunicorn
CMD exec gunicorn --bind 0.0.0.0:$PORT \
    --workers=2 \
    --threads=8 \
    --timeout=120 \
    --access-logfile=- \
    --error-logfile=- \
    "main:create_app()"
