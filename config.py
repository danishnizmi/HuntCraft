import os
from pathlib import Path
import google.auth

# Attempt to get GCP credentials
try:
    credentials, project_id = google.auth.default()
except Exception:
    credentials, project_id = None, None

# Base directory of the application
BASE_DIR = Path(__file__).resolve().parent

class Config:
    """Base configuration."""
    # Application settings
    DEBUG = os.environ.get('DEBUG', 'False') == 'True'
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key-for-development-only')
    APP_NAME = os.environ.get('APP_NAME', "Malware Detonation Platform")
    
    # Google Cloud Platform settings
    GCP_PROJECT_ID = os.environ.get('GCP_PROJECT_ID', project_id)
    GCP_REGION = os.environ.get('GCP_REGION', 'us-central1')
    GCP_ZONE = os.environ.get('GCP_ZONE', 'us-central1-a')
    
    # Check if running on Cloud Run
    ON_CLOUD_RUN = os.environ.get('K_SERVICE') is not None
    
    # Storage buckets
    GCP_STORAGE_BUCKET = os.environ.get('GCP_STORAGE_BUCKET', f"malware-samples-{GCP_PROJECT_ID}")
    GCP_RESULTS_BUCKET = os.environ.get('GCP_RESULTS_BUCKET', f"detonation-results-{GCP_PROJECT_ID}")
    
    # VM configuration
    VM_NETWORK = os.environ.get('VM_NETWORK', 'detonation-network')
    VM_SUBNET = os.environ.get('VM_SUBNET', 'detonation-subnet')
    VM_MACHINE_TYPE = os.environ.get('VM_MACHINE_TYPE', 'e2-medium')
    VM_IMAGE_FAMILY = os.environ.get('VM_IMAGE_FAMILY', 'detonation-vm')
    VM_IMAGE_PROJECT = os.environ.get('VM_IMAGE_PROJECT', GCP_PROJECT_ID)
    VM_SERVICE_ACCOUNT = os.environ.get('VM_SERVICE_ACCOUNT', f"detonation-vm@{GCP_PROJECT_ID}.iam.gserviceaccount.com")
    
    # Database settings - using SQLite
    # Ensure data directory exists
    if ON_CLOUD_RUN:
        os.makedirs('/app/data', exist_ok=True)
        DATABASE_PATH = os.environ.get('DATABASE_PATH', '/app/data/malware_platform.db')
    else:
        os.makedirs(os.path.join(BASE_DIR, 'data'), exist_ok=True)
        DATABASE_PATH = os.environ.get('DATABASE_PATH', os.path.join(BASE_DIR, 'data', 'malware_platform.db'))
    
    # Upload settings
    if ON_CLOUD_RUN:
        UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', '/app/data/uploads')
    else:
        UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(BASE_DIR, 'data', 'uploads'))
    
    # Create upload folder if it doesn't exist
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    
    # Max upload size - configurable via environment
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_UPLOAD_SIZE_MB', 100)) * 1024 * 1024
    
    # UI Theme settings - all configurable via environment variables
    PRIMARY_COLOR = os.environ.get('PRIMARY_COLOR', "#4a6fa5")
    SECONDARY_COLOR = os.environ.get('SECONDARY_COLOR', "#6c757d")
    DANGER_COLOR = os.environ.get('DANGER_COLOR', "#dc3545")
    SUCCESS_COLOR = os.environ.get('SUCCESS_COLOR', "#28a745")
    WARNING_COLOR = os.environ.get('WARNING_COLOR', "#ffc107")
    INFO_COLOR = os.environ.get('INFO_COLOR', "#17a2b8")
    DARK_COLOR = os.environ.get('DARK_COLOR', "#343a40")
    LIGHT_COLOR = os.environ.get('LIGHT_COLOR', "#f8f9fa")
    
    # Feature flags - configurable via environment
    ENABLE_ADVANCED_ANALYSIS = os.environ.get('ENABLE_ADVANCED_ANALYSIS', 'True') == 'True'
    ENABLE_DATA_EXPORT = os.environ.get('ENABLE_DATA_EXPORT', 'True') == 'True'
    ENABLE_VISUALIZATION = os.environ.get('ENABLE_VISUALIZATION', 'True') == 'True'
    
    # Detonation settings
    DETONATION_TIMEOUT_MINUTES = int(os.environ.get('DETONATION_TIMEOUT_MINUTES', 15))
    MAX_CONCURRENT_DETONATIONS = int(os.environ.get('MAX_CONCURRENT_DETONATIONS', 5))
    
    # Logging configuration
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')

class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True

class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    
    def __init__(self):
        # Ensure SECRET_KEY is set for production
        if os.environ.get('SECRET_KEY') == 'dev-key-for-development-only':
            import secrets
            os.environ['SECRET_KEY'] = secrets.token_hex(16)
            self.SECRET_KEY = os.environ['SECRET_KEY']

class TestConfig(Config):
    """Test configuration."""
    TESTING = True
    DEBUG = True
    
    # Use in-memory database for testing
    DATABASE_PATH = ":memory:"
