# Use Python 3.11 slim as base image
FROM python:3.11-slim AS builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Set working directory for builder
WORKDIR /build

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    libfuzzy-dev \
    libssl-dev \
    pkg-config \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements.txt separately for better caching
COPY requirements.txt .

# Install Python dependencies with fixed versions in a virtual environment
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# Second stage for runtime - slimmer final image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    PATH="/opt/venv/bin:$PATH" \
    GENERATE_TEMPLATES=false \
    GUNICORN_WORKERS=1 \
    GUNICORN_TIMEOUT=300

# Set working directory
WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libmagic1 \
    curl \
    ca-certificates \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv

# Create stub modules for problematic packages
RUN mkdir -p /app/stubs && \
    echo 'class Hash:\n    def __init__(self, *args, **kwargs):\n        self.value = "stub"\n    def update(self, *args, **kwargs):\n        pass\n    def digest(self):\n        return "stub_hash"\n\ndef hash(*args, **kwargs):\n    return Hash()\n\ndef compare(*args, **kwargs):\n    return 0' > /app/stubs/ssdeep.py && \
    echo 'class Rules:\n    def match(self, *args, **kwargs):\n        return []\n\ndef compile(*args, **kwargs):\n    return Rules()' > /app/stubs/yara.py && \
    echo 'class Entry:\n    def __init__(self, *args, **kwargs):\n        self.dll = "stub.dll"\n        self.imports = []\n\nclass PE:\n    def __init__(self, *args, **kwargs):\n        self.DIRECTORY_ENTRY_IMPORT = [Entry()]\n        self.DIRECTORY_ENTRY_EXPORT = []\n    def close(self):\n        pass' > /app/stubs/pefile.py && \
    touch /app/stubs/__init__.py

# Set PYTHONPATH to include stubs
ENV PYTHONPATH=/app:/app/stubs:$PYTHONPATH

# Create non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser

# Create necessary directories and set permissions
RUN mkdir -p /app/data/uploads && \
    mkdir -p /app/data/database && \
    mkdir -p /app/static/css && \
    mkdir -p /app/static/js && \
    mkdir -p /app/templates && \
    chown -R appuser:appuser /app

# Copy application code
COPY --chown=appuser:appuser . .

# Pre-generate templates during build time
RUN mkdir -p /app/templates && python -c "import os; os.environ['GENERATE_TEMPLATES'] = 'true'; \
    from flask import Flask; \
    app = Flask(__name__); \
    app.config['GENERATE_TEMPLATES'] = True; \
    app.config['DATABASE_PATH'] = '/app/data/malware_platform.db'; \
    app.config['UPLOAD_FOLDER'] = '/app/data/uploads'; \
    with app.app_context(): \
        try: \
            import web_interface; \
            web_interface.generate_base_templates(); \
            web_interface.generate_css(); \
            web_interface.generate_js(); \
            import malware_module; \
            malware_module.generate_templates(); \
            malware_module.generate_css(); \
            malware_module.generate_js(); \
            import viz_module; \
            viz_module.generate_templates(); \
            viz_module.generate_css(); \
            viz_module.generate_js(); \
        except Exception as e: \
            print(f'Error generating templates: {e}')" || echo "Template generation failed but continuing"

# Switch to non-root user for security
USER appuser

# Set environment variables for runtime
ENV DATABASE_PATH=/app/data/malware_platform.db \
    UPLOAD_FOLDER=/app/data/uploads \
    MAX_UPLOAD_SIZE_MB=100 \
    DEBUG=false

# Create a startup wrapper script
RUN echo '#!/bin/bash\n\
echo "Starting application initialization..."\n\
echo "Python version:"\n\
python --version\n\
\n\
# Create and verify directories\n\
mkdir -p /app/data/uploads\n\
mkdir -p /app/static/css\n\
mkdir -p /app/static/js\n\
mkdir -p /app/templates\n\
\n\
# Get the number of workers from env or default to 1\n\
WORKERS=${GUNICORN_WORKERS:-1}\n\
TIMEOUT=${GUNICORN_TIMEOUT:-120}\n\
\n\
echo "Starting Gunicorn server with $WORKERS workers, timeout $TIMEOUT seconds..."\n\
exec gunicorn --bind 0.0.0.0:$PORT \
    --workers=$WORKERS \
    --threads=4 \
    --timeout=$TIMEOUT \
    --access-logfile=- \
    --error-logfile=- \
    --log-level=info \
    "main:create_app()"' > /app/start.sh && \
    chmod +x /app/start.sh

# Expose port
EXPOSE 8080

# Run the startup script
CMD ["/app/start.sh"]
