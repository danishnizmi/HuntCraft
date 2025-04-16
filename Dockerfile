# Use Python 3.11 slim as base image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies required for building Python packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    libfuzzy-dev \
    libssl-dev \
    libmagic-dev \
    git \
    wget \
    unzip \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies for yara-python
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    automake \
    libtool \
    make \
    pkg-config \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create required directories
RUN mkdir -p /app/data/uploads && \
    mkdir -p /app/data/malware_samples && \
    mkdir -p /app/data/detonation_results && \
    mkdir -p /app/logs

# Set proper permissions
RUN chmod -R 755 /app

# Create static folders if they don't exist
RUN mkdir -p /app/static/css && \
    mkdir -p /app/static/js && \
    mkdir -p /app/templates

# Expose the application port
EXPOSE 8080

# Run the application with gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--timeout", "120", "--workers", "3", "main:create_app()"]
