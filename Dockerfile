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

# Create a clean requirements file without problematic packages
RUN echo "# Core framework\n\
Flask==2.3.3\n\
Werkzeug==2.3.7\n\
Jinja2==3.1.2\n\
gunicorn==21.2.0\n\
Flask-Login==0.6.2\n\
\n\
# Database\n\
SQLAlchemy==2.0.20\n\
psycopg2-binary==2.9.7\n\
\n\
# GCP libraries\n\
google-cloud-storage==2.10.0\n\
google-cloud-compute==1.12.0\n\
google-cloud-logging==3.5.0\n\
google-cloud-monitoring==2.15.0\n\
google-cloud-secret-manager==2.16.2\n\
google-cloud-pubsub==2.18.4\n\
google-auth==2.22.0\n\
google-cloud-functions==1.13.1\n\
\n\
# Data processing\n\
pandas==2.0.3\n\
numpy==1.24.4\n\
\n\
# Security and file analysis\n\
python-magic==0.4.27\n\
\n\
# Visualization\n\
plotly==5.15.0\n\
\n\
# Utilities\n\
requests==2.31.0\n\
urllib3==2.0.4\n\
six==1.16.0\n\
python-dateutil==2.8.2\n\
pytz==2023.3" > /app/requirements-clean.txt

# Install Python dependencies from the clean requirements file
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements-clean.txt

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
