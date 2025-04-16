import os
from pathlib import Path
from google.cloud import secretmanager

class Config:
    """Base configuration with GCP integration"""
    # Core settings
    PROJECT_ID = os.environ.get('GCP_PROJECT_ID') or os.environ.get('GOOGLE_CLOUD_PROJECT')
    ON_CLOUD_RUN = os.environ.get('K_SERVICE') is not None
    DEBUG = os.environ.get('DEBUG', 'False').lower() in ('true', '1', 't')
    APP_NAME = os.environ.get('APP_NAME', "Malware Detonation Platform")
    
    # GCP settings
    GCP_REGION = os.environ.get('GCP_REGION', 'us-central1')
    GCP_ZONE = os.environ.get('GCP_ZONE', 'us-central1-a')
    
    # Secret Manager integration
    @classmethod
    def get_secret(cls, secret_id, version="latest"):
        """Get secret from Secret Manager or environment fallback"""
        if cls.ON_CLOUD_RUN and cls.PROJECT_ID:
            try:
                client = secretmanager.SecretManagerServiceClient()
                name = f"projects/{cls.PROJECT_ID}/secrets/{secret_id}/versions/{version}"
                response = client.access_secret_version(request={"name": name})
                return response.payload.data.decode("UTF-8")
            except Exception:
                pass
        return os.environ.get(secret_id, f"dev-value-for-{secret_id}")
    
    # Secret values
    SECRET_KEY = get_secret.__func__("SECRET_KEY")
    
    # Storage configuration
    if ON_CLOUD_RUN:
        DATABASE_PATH = '/app/data/malware_platform.db'
        UPLOAD_FOLDER = '/app/data/uploads'
        GCP_STORAGE_BUCKET = f"malware-samples-{PROJECT_ID}" if PROJECT_ID else "malware-samples"
        GCP_RESULTS_BUCKET = f"detonation-results-{PROJECT_ID}" if PROJECT_ID else "detonation-results"
    else:
        BASE_DIR = Path(__file__).resolve().parent
        DATABASE_PATH = os.path.join(BASE_DIR, 'data', 'malware_platform.db')
        UPLOAD_FOLDER = os.path.join(BASE_DIR, 'data', 'uploads')
        GCP_STORAGE_BUCKET = f"malware-samples-dev-{PROJECT_ID}" if PROJECT_ID else "malware-samples-local"
        GCP_RESULTS_BUCKET = f"detonation-results-dev-{PROJECT_ID}" if PROJECT_ID else "detonation-results-local"
    
    # VM configuration
    VM_NETWORK = os.environ.get('VM_NETWORK', 'detonation-network')
    VM_SUBNET = os.environ.get('VM_SUBNET', 'detonation-subnet')
    VM_MACHINE_TYPE = os.environ.get('VM_MACHINE_TYPE', 'e2-medium')
    VM_IMAGE_FAMILY = os.environ.get('VM_IMAGE_FAMILY', 'detonation-vm')
    VM_SERVICE_ACCOUNT = os.environ.get('VM_SERVICE_ACCOUNT', f"detonation-vm@{PROJECT_ID}.iam.gserviceaccount.com")
    
    # Upload and feature limits
    MAX_UPLOAD_SIZE_MB = int(os.environ.get('MAX_UPLOAD_SIZE_MB', 100))
    MAX_CONTENT_LENGTH = MAX_UPLOAD_SIZE_MB * 1024 * 1024
    DETONATION_TIMEOUT_MINUTES = int(os.environ.get('DETONATION_TIMEOUT_MINUTES', 15))
    MAX_CONCURRENT_DETONATIONS = int(os.environ.get('MAX_CONCURRENT_DETONATIONS', 5))
    
    # UI configuration
    PRIMARY_COLOR = os.environ.get('PRIMARY_COLOR', '#4a6fa5')
    SECONDARY_COLOR = os.environ.get('SECONDARY_COLOR', '#6c757d')
    DANGER_COLOR = os.environ.get('DANGER_COLOR', '#dc3545')
    SUCCESS_COLOR = os.environ.get('SUCCESS_COLOR', '#28a745')
    WARNING_COLOR = os.environ.get('WARNING_COLOR', '#ffc107')
    INFO_COLOR = os.environ.get('INFO_COLOR', '#17a2b8')
    DARK_COLOR = os.environ.get('DARK_COLOR', '#343a40')
    LIGHT_COLOR = os.environ.get('LIGHT_COLOR', '#f8f9fa')
    
    # Feature flags
    ENABLE_ADVANCED_ANALYSIS = os.environ.get('ENABLE_ADVANCED_ANALYSIS', 'True').lower() in ('true', '1', 't')
    ENABLE_DATA_EXPORT = os.environ.get('ENABLE_DATA_EXPORT', 'True').lower() in ('true', '1', 't')
    ENABLE_VISUALIZATION = os.environ.get('ENABLE_VISUALIZATION', 'True').lower() in ('true', '1', 't')
