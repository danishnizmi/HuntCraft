import os
import logging
from pathlib import Path
from google.cloud import secretmanager
import json

# Configure logger
logger = logging.getLogger(__name__)

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
    
    # Storage configuration - Fixed to prevent GCP_STORAGE_BUCKET error
    if ON_CLOUD_RUN:
        DATABASE_PATH = '/app/data/malware_platform.db'
        UPLOAD_FOLDER = '/app/data/uploads'
        
        # Use environment variable if provided, otherwise construct from PROJECT_ID
        GCP_STORAGE_BUCKET = os.environ.get('GCP_STORAGE_BUCKET')
        if not GCP_STORAGE_BUCKET and PROJECT_ID:
            GCP_STORAGE_BUCKET = f"malware-samples-{PROJECT_ID}"
        elif not GCP_STORAGE_BUCKET:
            GCP_STORAGE_BUCKET = "malware-samples-default"
            logger.warning("No GCP_STORAGE_BUCKET or PROJECT_ID provided, using default bucket name")
        
        # Use environment variable if provided, otherwise construct from PROJECT_ID
        GCP_RESULTS_BUCKET = os.environ.get('GCP_RESULTS_BUCKET')
        if not GCP_RESULTS_BUCKET and PROJECT_ID:
            GCP_RESULTS_BUCKET = f"detonation-results-{PROJECT_ID}"
        elif not GCP_RESULTS_BUCKET:
            GCP_RESULTS_BUCKET = "detonation-results-default"
            logger.warning("No GCP_RESULTS_BUCKET or PROJECT_ID provided, using default bucket name")
        
        # Store bucket access test results
        try:
            from google.cloud import storage
            client = storage.Client()
            # Test if buckets exist and are accessible
            buckets_exist = True
            try:
                client.get_bucket(GCP_STORAGE_BUCKET)
                logger.info(f"Successfully connected to bucket: {GCP_STORAGE_BUCKET}")
            except Exception as e:
                logger.warning(f"Could not access storage bucket {GCP_STORAGE_BUCKET}: {str(e)}")
                buckets_exist = False
                
            # Set flag to indicate if we should use local storage as fallback
            USE_LOCAL_STORAGE = not buckets_exist
        except Exception as e:
            logger.warning(f"Error initializing GCP storage client: {str(e)}")
            USE_LOCAL_STORAGE = True
    else:
        BASE_DIR = Path(__file__).resolve().parent
        DATABASE_PATH = os.path.join(BASE_DIR, 'data', 'malware_platform.db')
        UPLOAD_FOLDER = os.path.join(BASE_DIR, 'data', 'uploads')
        GCP_STORAGE_BUCKET = f"malware-samples-dev-{PROJECT_ID}" if PROJECT_ID else "malware-samples-local"
        GCP_RESULTS_BUCKET = f"detonation-results-dev-{PROJECT_ID}" if PROJECT_ID else "detonation-results-local"
        # Default to local storage in dev environment
        USE_LOCAL_STORAGE = True
    
    # VM configuration
    VM_NETWORK = os.environ.get('VM_NETWORK', 'detonation-network')
    VM_SUBNET = os.environ.get('VM_SUBNET', 'detonation-subnet')
    VM_MACHINE_TYPE = os.environ.get('VM_MACHINE_TYPE', 'e2-medium')
    VM_IMAGE_FAMILY = os.environ.get('VM_IMAGE_FAMILY', 'detonation-vm')
    VM_SERVICE_ACCOUNT = os.environ.get(
        'VM_SERVICE_ACCOUNT', 
        f"detonation-vm@{PROJECT_ID}.iam.gserviceaccount.com" if PROJECT_ID else "detonation-vm@example.com"
    )
    
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
    
    @classmethod
    def get_secret(cls, secret_id, version="latest"):
        """Get secret from Secret Manager or environment fallback
        
        Args:
            secret_id (str): The secret ID to retrieve
            version (str): The version of the secret to retrieve
            
        Returns:
            str: The secret value
        """
        if not secret_id:
            logger.warning("No secret_id provided to get_secret")
            return None
            
        # First try to get from environment variables (safer for local dev)
        env_value = os.environ.get(secret_id)
        if env_value:
            logger.debug(f"Using environment value for secret: {secret_id}")
            return env_value
            
        # Next try Secret Manager if on Cloud Run
        if cls.ON_CLOUD_RUN and cls.PROJECT_ID:
            try:
                logger.debug(f"Attempting to retrieve secret from Secret Manager: {secret_id}")
                client = secretmanager.SecretManagerServiceClient()
                name = f"projects/{cls.PROJECT_ID}/secrets/{secret_id}/versions/{version}"
                response = client.access_secret_version(request={"name": name})
                return response.payload.data.decode("UTF-8")
            except Exception as e:
                logger.warning(f"Failed to retrieve secret from Secret Manager: {str(e)}")
        
        # Return a development value only if DEBUG is True
        if cls.DEBUG:
            # Generate a deterministic but not easily guessable value for development
            import hashlib
            dev_value = hashlib.sha256(f"dev-{secret_id}-{cls.PROJECT_ID or 'local'}".encode()).hexdigest()[:16]
            logger.warning(f"Using generated development value for {secret_id}")
            return dev_value
        else:
            logger.error(f"No secret value found for {secret_id} and not in debug mode")
            return None

    @classmethod
    def get_storage_info(cls):
        """Get storage information for diagnostics and troubleshooting"""
        return {
            "storage_mode": "GCP" if not getattr(cls, 'USE_LOCAL_STORAGE', True) else "Local",
            "storage_bucket": cls.GCP_STORAGE_BUCKET,
            "results_bucket": cls.GCP_RESULTS_BUCKET,
            "upload_folder": cls.UPLOAD_FOLDER,
            "on_cloud_run": cls.ON_CLOUD_RUN,
            "project_id": cls.PROJECT_ID
        }

# Set SECRET_KEY safely
# Try to get from environment or Secret Manager or generate a secure one
try:
    SECRET_KEY = Config.get_secret("SECRET_KEY")
    if not SECRET_KEY:
        # If still no SECRET_KEY, generate one in debug mode or raise error
        if Config.DEBUG:
            import secrets
            SECRET_KEY = secrets.token_hex(32)
            logger.warning("Generated random SECRET_KEY for debug mode")
        else:
            # In production without a key, log error but don't crash
            SECRET_KEY = "MISSING_SECRET_KEY"
            logger.error("SECRET_KEY is missing in production mode! Using placeholder but this is NOT secure.")
    # Add SECRET_KEY to Config class namespace
    setattr(Config, 'SECRET_KEY', SECRET_KEY)
except Exception as e:
    logger.error(f"Error setting SECRET_KEY: {str(e)}")
    # Set a fallback in case of error, but log prominently
    setattr(Config, 'SECRET_KEY', os.environ.get('SECRET_KEY', 'emergency-fallback-key-not-secure'))
    logger.error("Using emergency fallback SECRET_KEY - this is NOT secure for production!")

# Export storage config for diagnostic endpoints
try:
    storage_info = Config.get_storage_info()
    logger.info(f"Storage configuration: {json.dumps(storage_info)}")
except Exception as e:
    logger.error(f"Error getting storage info: {str(e)}")
