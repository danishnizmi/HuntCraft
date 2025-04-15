import os
from pathlib import Path

# Base directory of the application
BASE_DIR = Path(__file__).resolve().parent

class Config:
    """Base configuration."""
    # Application settings
    DEBUG = os.environ.get('DEBUG', 'True') == 'True'
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key-for-development-only')
    APP_NAME = "Threat Hunting Workbench"
    
    # Database settings - using SQLite for Render's free tier
    DATABASE_PATH = os.path.join(BASE_DIR, 'data', 'threat_hunting.db')
    
    # Upload settings
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'data', 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB max upload
    
    # UI Theme settings
    PRIMARY_COLOR = "#4a6fa5"
    SECONDARY_COLOR = "#6c757d"
    DANGER_COLOR = "#dc3545"
    SUCCESS_COLOR = "#28a745"
    WARNING_COLOR = "#ffc107"
    INFO_COLOR = "#17a2b8"
    DARK_COLOR = "#343a40"
    LIGHT_COLOR = "#f8f9fa"
    
    # Feature flags
    ENABLE_ADVANCED_ANALYSIS = True
    ENABLE_DATA_EXPORT = True
    ENABLE_VISUALIZATION = True

class TestConfig(Config):
    """Test configuration."""
    TESTING = True
    DEBUG = True
    
    # Use in-memory database for testing
    DATABASE_PATH = ":memory:"
