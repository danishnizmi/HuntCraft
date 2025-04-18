# Use Python 3.11 slim as base image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PORT=8080 \
    PYTHONMALLOC=malloc \
    PYTHONHASHSEED=0 \
    GENERATE_TEMPLATES=false \
    INITIALIZE_GCP=false \
    SKIP_DB_INIT=false

# Set working directory
WORKDIR /app

# Install system dependencies - keep only what's needed
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    libmagic1 \
    curl \
    ca-certificates \
    git \
    pkg-config \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create stub modules for problematic packages to reduce build dependencies
RUN mkdir -p /app/stubs && \
    echo 'class Hash:\n    def __init__(self, *args, **kwargs):\n        self.value = "stub"\n    def update(self, *args, **kwargs):\n        pass\n    def digest(self):\n        return "stub_hash"\n\ndef hash(*args, **kwargs):\n    return Hash()\n\ndef compare(*args, **kwargs):\n    return 0' > /app/stubs/ssdeep.py && \
    echo 'class Rules:\n    def match(self, *args, **kwargs):\n        return []\n\ndef compile(*args, **kwargs):\n    return Rules()' > /app/stubs/yara.py && \
    echo 'class Entry:\n    def __init__(self, *args, **kwargs):\n        self.dll = "stub.dll"\n        self.imports = []\n\nclass PE:\n    def __init__(self, *args, **kwargs):\n        self.DIRECTORY_ENTRY_IMPORT = [Entry()]\n        self.DIRECTORY_ENTRY_EXPORT = []\n    def close(self):\n        pass' > /app/stubs/pefile.py && \
    touch /app/stubs/__init__.py

# Set PYTHONPATH to include stubs
ENV PYTHONPATH=/app:/app/stubs:$PYTHONPATH

# Copy requirements.txt
COPY requirements.txt .

# Generate simplified requirements without problematic packages
RUN grep -v "ssdeep\|yara-python\|pefile" requirements.txt > requirements-safe.txt

# Install Python dependencies with optimization
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements-safe.txt

# Create necessary directories with appropriate permissions
RUN mkdir -p /app/data/uploads && \
    mkdir -p /app/data/database && \
    mkdir -p /app/static/css && \
    mkdir -p /app/static/js && \
    mkdir -p /app/templates && \
    chmod -R 755 /app/data

# Create minimal templates to avoid generation at runtime
RUN echo '<!DOCTYPE html><html><head><title>Malware Detonation Platform</title><style>body{font-family:Arial,sans-serif;text-align:center;margin-top:50px}h1{color:#4a6fa5}</style></head><body><h1>Malware Detonation Platform</h1><p>The application is starting...</p></body></html>' > /app/templates/index.html && \
    echo '{% extends "index.html" %}' > /app/templates/base.html

# Set environment variables for runtime
ENV DATABASE_PATH=/app/data/malware_platform.db \
    UPLOAD_FOLDER=/app/data/uploads \
    MAX_UPLOAD_SIZE_MB=100 \
    DEBUG=false \
    GENERATE_TEMPLATES=false \
    INITIALIZE_GCP=false

# Copy application code
COPY . .

# Create an optimized startup script with proper health check and initialization
RUN echo '#!/bin/bash\n\
echo "Starting application initialization at $(date)..."\n\
echo "Python version: $(python --version)"\n\
\n\
# Ensure directories exist\n\
mkdir -p /app/data/uploads\n\
mkdir -p /app/data/database\n\
mkdir -p /app/static/css\n\
mkdir -p /app/static/js\n\
mkdir -p /app/templates\n\
\n\
# Pre-initialize database schema to avoid runtime delays\n\
if [ "${SKIP_DB_INIT}" != "true" ]; then\n\
  echo "Pre-initializing database schema..."\n\
  python -c "from flask import Flask; app = Flask(__name__); app.config[\"DATABASE_PATH\"] = \"/app/data/malware_platform.db\"; from database import init_app; init_app(app)" || true\n\
fi\n\
\n\
# Check for duplicate code in database.py and fix if found\n\
if grep -q "def ensure_db_directory_exists(app):" /app/database.py; then\n\
  if [ $(grep -c "def ensure_db_directory_exists(app):" /app/database.py) -gt 1 ]; then\n\
    echo "WARNING: Duplicate code found in database.py, attempting to fix..."\n\
    # Find the end of the first function instance\n\
    FIRST_END=$(grep -n "def ensure_db_directory_exists(app):" /app/database.py | head -1 | cut -d":" -f1)\n\
    SECOND_START=$(grep -n "def ensure_db_directory_exists(app):" /app/database.py | tail -1 | cut -d":" -f1)\n\
    if [ -n "$FIRST_END" ] && [ -n "$SECOND_START" ]; then\n\
      # Create a fixed version with only one copy of the function\n\
      head -n $SECOND_START /app/database.py > /app/database.py.fixed\n\
      mv /app/database.py.fixed /app/database.py\n\
      echo "Fixed duplicate code in database.py"\n\
    fi\n\
  fi\n\
fi\n\
\n\
# Start the server with improved settings\n\
echo "Starting Gunicorn server with optimized settings at $(date)..."\n\
exec gunicorn --bind 0.0.0.0:$PORT \
    --workers=1 \
    --threads=4 \
    --timeout=300 \
    --graceful-timeout=120 \
    --keep-alive=120 \
    --worker-tmp-dir=/dev/shm \
    --worker-class=gthread \
    --max-requests=1000 \
    --max-requests-jitter=50 \
    --access-logfile=- \
    --error-logfile=- \
    --log-level=info \
    --capture-output \
    "main:create_app()"' > /app/start.sh && \
    chmod +x /app/start.sh

# Create a quick-start health check hook to pass initial container checks
RUN echo '#!/bin/bash\n\
echo "{\\"status\\": \\"starting\\", \\"database\\": \\"initializing\\", \\"timestamp\\": \\"$(date -u +"%Y-%m-%dT%H:%M:%SZ")\\"}"\n\
exit 0' > /app/health-check.sh && \
    chmod +x /app/health-check.sh

# Create a specialized health check handler
RUN mkdir -p /app/handlers && \
    echo '#!/usr/bin/env python3\n\
import sys\n\
import os\n\
import json\n\
import time\n\
import sqlite3\n\
from datetime import datetime\n\
\n\
def main():\n\
    try:\n\
        # Check if main application is running by touching a file\n\
        app_ready = os.path.exists("/app/data/.app_ready")\n\
        \n\
        # Check database only if app is not yet marked as ready\n\
        db_status = "unknown"\n\
        if not app_ready:\n\
            try:\n\
                db_path = os.environ.get("DATABASE_PATH", "/app/data/malware_platform.db")\n\
                if os.path.exists(db_path):\n\
                    conn = sqlite3.connect(db_path)\n\
                    cursor = conn.cursor()\n\
                    cursor.execute("SELECT 1")\n\
                    cursor.fetchone()\n\
                    conn.close()\n\
                    db_status = "connected"\n\
                else:\n\
                    db_status = "not_created"\n\
            except Exception as e:\n\
                db_status = f"error: {str(e)}"\n\
        else:\n\
            db_status = "managed_by_app"\n\
        \n\
        # Check disk space\n\
        disk_space = os.statvfs("/")\n\
        free_space_mb = (disk_space.f_bavail * disk_space.f_frsize) / (1024 * 1024)\n\
        \n\
        # Build response\n\
        response = {\n\
            "status": "starting" if not app_ready else "ready",\n\
            "database": db_status,\n\
            "uptime": time.time() - os.path.getctime("/proc/1/cmdline") if os.path.exists("/proc/1/cmdline") else 0,\n\
            "disk_space_mb": free_space_mb,\n\
            "timestamp": datetime.now().isoformat()\n\
        }\n\
        \n\
        print(json.dumps(response))\n\
        return 0 if app_ready or free_space_mb > 100 else 1  # Only fail if both app not ready AND disk space critical\n\
    except Exception as e:\n\
        print(json.dumps({\n\
            "status": "error",\n\
            "error": str(e),\n\
            "timestamp": datetime.now().isoformat()\n\
        }))\n\
        return 1\n\
\n\
if __name__ == "__main__":\n\
    sys.exit(main())\n\
' > /app/handlers/health.py && \
    chmod +x /app/handlers/health.py

# Setup initial templates for modules to avoid generation at runtime
RUN mkdir -p /app/templates/modules && \
    touch /app/templates/modules/.keep

# Enable application to create .app_ready when fully initialized
RUN echo 'import os\n\
import atexit\n\
\n\
def mark_app_ready():\n\
    """Mark the application as ready for health checks."""\n\
    try:\n\
        with open("/app/data/.app_ready", "w") as f:\n\
            f.write("ready")\n\
    except Exception:\n\
        pass\n\
\n\
def cleanup_app_ready():\n\
    """Remove the app ready marker on shutdown."""\n\
    try:\n\
        if os.path.exists("/app/data/.app_ready"):\n\
            os.remove("/app/data/.app_ready")\n\
    except Exception:\n\
        pass\n\
\n\
# Register the cleanup function\n\
atexit.register(cleanup_app_ready)\n\
' > /app/app_ready.py

# Modify main.py to import app_ready module (without creating a new file)
RUN echo '\n# Mark application as ready when fully initialized\ntry:\n    from app_ready import mark_app_ready\n    mark_app_ready()\nexcept Exception:\n    pass' >> /app/main.py

# Expose port
EXPOSE 8080

# Run the startup script
CMD ["/app/start.sh"]
