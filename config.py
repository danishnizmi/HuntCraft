# config.py - Optimized version
import os
from pathlib import Path
from google.cloud import secretmanager

class Config:
    """Base configuration using GCP Secret Manager for sensitive values"""
    # Get project ID from metadata server or environment
    PROJECT_ID = os.environ.get('GCP_PROJECT_ID') or os.environ.get('GOOGLE_CLOUD_PROJECT')
    
    # Check if running on Cloud Run
    ON_CLOUD_RUN = os.environ.get('K_SERVICE') is not None
    
    # Load secrets from Secret Manager
    @classmethod
    def get_secret(cls, secret_id, version="latest"):
        """Get secret from Secret Manager or use default in development"""
        if cls.ON_CLOUD_RUN:
            try:
                client = secretmanager.SecretManagerServiceClient()
                name = f"projects/{cls.PROJECT_ID}/secrets/{secret_id}/versions/{version}"
                response = client.access_secret_version(request={"name": name})
                return response.payload.data.decode("UTF-8")
            except Exception as e:
                print(f"Error accessing secret {secret_id}: {e}")
                
        # Fallback to environment variable or default
        return os.environ.get(secret_id, f"dev-value-for-{secret_id}")
    
    # Application settings
    SECRET_KEY = get_secret.__func__("SECRET_KEY")
    APP_NAME = os.environ.get('APP_NAME', "Malware Detonation Platform")
    DEBUG = os.environ.get('DEBUG', 'False') == 'True'
    
    # GCP settings (get from environment or compute engine metadata)
    GCP_REGION = os.environ.get('GCP_REGION', 'us-central1')
    GCP_ZONE = os.environ.get('GCP_ZONE', 'us-central1-a')
    
    # Database and storage setup - tailored for Cloud Run
    if ON_CLOUD_RUN:
        DATABASE_PATH = '/app/data/malware_platform.db'
        UPLOAD_FOLDER = '/app/data/uploads'
        GCP_STORAGE_BUCKET = f"malware-samples-{PROJECT_ID}"
        GCP_RESULTS_BUCKET = f"detonation-results-{PROJECT_ID}"
    else:
        BASE_DIR = Path(__file__).resolve().parent
        DATABASE_PATH = os.path.join(BASE_DIR, 'data', 'malware_platform.db')
        UPLOAD_FOLDER = os.path.join(BASE_DIR, 'data', 'uploads')
        GCP_STORAGE_BUCKET = f"malware-samples-dev-{PROJECT_ID}" if PROJECT_ID else "malware-samples-local"
        GCP_RESULTS_BUCKET = f"detonation-results-dev-{PROJECT_ID}" if PROJECT_ID else "detonation-results-local"
    
    # VM configuration with defaults from environment
    VM_NETWORK = os.environ.get('VM_NETWORK', 'detonation-network')
    VM_SUBNET = os.environ.get('VM_SUBNET', 'detonation-subnet')
    VM_MACHINE_TYPE = os.environ.get('VM_MACHINE_TYPE', 'e2-medium')
    VM_IMAGE_FAMILY = os.environ.get('VM_IMAGE_FAMILY', 'detonation-vm')
    VM_SERVICE_ACCOUNT = os.environ.get('VM_SERVICE_ACCOUNT', f"detonation-vm@{PROJECT_ID}.iam.gserviceaccount.com")
    
    # Feature flags and other settings
    MAX_UPLOAD_SIZE_MB = int(os.environ.get('MAX_UPLOAD_SIZE_MB', 100))
    MAX_CONTENT_LENGTH = MAX_UPLOAD_SIZE_MB * 1024 * 1024
    DETONATION_TIMEOUT_MINUTES = int(os.environ.get('DETONATION_TIMEOUT_MINUTES', 15))
    MAX_CONCURRENT_DETONATIONS = int(os.environ.get('MAX_CONCURRENT_DETONATIONS', 5))
