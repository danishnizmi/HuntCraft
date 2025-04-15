import os
from pathlib import Path

# Base directory of the application
BASE_DIR = Path(__file__).resolve().parent

class Config:
    """Base configuration."""
    # Application settings
    DEBUG = os.environ.get('DEBUG', 'True') == 'True'
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key-for-development-only')
    APP_NAME = os.environ.get('APP_NAME', "Threat Hunting Workbench")
    
    # Detect if running on Render
    ON_RENDER = os.environ.get('RENDER', '') == 'true'
    
    # Database settings - using SQLite
    # Ensure data directory exists in Render environment
    if ON_RENDER:
        os.makedirs(os.path.join(BASE_DIR, 'data'), exist_ok=True)
        
    DATABASE_PATH = os.environ.get('DATABASE_PATH', 
                                  os.path.join(BASE_DIR, 'data', 'threat_hunting.db'))
    
    # Upload settings
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER',
                                  os.path.join(BASE_DIR, 'data', 'uploads'))
    # Create upload folder if it doesn't exist
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    
    # Max upload size - configurable via environment
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_UPLOAD_SIZE_MB', 16)) * 1024 * 1024
    
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
