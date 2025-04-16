from flask import Flask, current_app
import os
import sqlite3
import logging
import importlib
from pathlib import Path
from google.cloud import logging as gcp_logging

# Module configuration - Fixed to use existing module names
MODULES = {
    'malware': 'malware_module',  # Handles malware samples
    'detonation': 'detonation_module',  # Handles VM detonation
    'viz': 'viz_module',  # Fixed to use the actual module name (viz_module instead of results_module)
    'web': 'web_interface_module'  # Web interface
}

def create_app(test_config=None):
    """Application factory to create and configure the Flask app"""
    # Create and configure the app
    app = Flask(__name__, 
                static_folder='static',
                template_folder='templates')
    
    # Configure logging
    setup_logging(app)
    logger = logging.getLogger(__name__)
    
    # Load configuration
    try:
        import config
        app.config.from_object(config.Config if not test_config else test_config)
        logger.info("Configuration loaded successfully")
    except Exception as e:
        logger.error(f"Error loading configuration: {str(e)}")
        # Set fallback configuration
        app.config.update(
            SECRET_KEY=os.environ.get('SECRET_KEY', 'dev-key'),
            DATABASE_PATH=os.environ.get('DATABASE_PATH', '/app/data/malware_platform.db'),
            UPLOAD_FOLDER=os.environ.get('UPLOAD_FOLDER', '/app/data/uploads'),
            MAX_UPLOAD_SIZE_MB=int(os.environ.get('MAX_UPLOAD_SIZE_MB', 100)),
            DEBUG=os.environ.get('DEBUG', 'False').lower() in ('true', '1', 't'),
            APP_NAME=os.environ.get('APP_NAME', "Malware Detonation Platform"),
            GCP_PROJECT_ID=os.environ.get('GCP_PROJECT_ID', ''),
            GCP_REGION=os.environ.get('GCP_REGION', 'us-central1'),
            GCP_ZONE=os.environ.get('GCP_ZONE', 'us-central1-a'),
            PRIMARY_COLOR='#4a6fa5',
            SECONDARY_COLOR='#6c757d',
            DANGER_COLOR='#dc3545',
            SUCCESS_COLOR='#28a745',
            WARNING_COLOR='#ffc107',
            INFO_COLOR='#17a2b8',
            DARK_COLOR='#343a40',
            LIGHT_COLOR='#f8f9fa',
            ENABLE_ADVANCED_ANALYSIS=True,
            ENABLE_DATA_EXPORT=True,
            ENABLE_VISUALIZATION=True
        )
    
    # Setup required directories 
    _setup_directories(app)
    
    # Initialize database
    with app.app_context():
        try:
            _init_database()
        except Exception as e:
            logger.error(f"Database initialization error: {str(e)}")
    
    # Load and register all modules
    _load_modules(app)
    
    # Register error handlers
    @app.errorhandler(404)
    def page_not_found(e):
        try:
            mod = importlib.import_module(MODULES['web'])
            if hasattr(mod, 'handle_404'):
                return mod.handle_404(), 404
        except:
            pass
        return "Page not found", 404

    @app.errorhandler(500)
    def server_error(e):
        try:
            mod = importlib.import_module(MODULES['web'])
            if hasattr(mod, 'handle_500'):
                return mod.handle_500(), 500
        except:
            pass
        return "Server error", 500
        
    # Add health check endpoint for Cloud Run
    @app.route('/health')
    def health_check():
        return {'status': 'healthy'}, 200
    
    logger.info("Application setup complete")
    return app

def setup_logging(app):
    """Set up logging with GCP integration if available"""
    # Check if we're running on Cloud Run
    on_cloud_run = os.environ.get('K_SERVICE') is not None
    
    if on_cloud_run:
        # Set up Google Cloud Logging
        try:
            client = gcp_logging.Client()
            client.setup_logging(log_level=logging.INFO)
            app.logger.info("Google Cloud Logging initialized")
        except Exception as e:
            # Fall back to standard logging
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            app.logger.warning(f"Failed to initialize Google Cloud Logging: {str(e)}")
    else:
        # Standard logging for local development
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

def _setup_directories(app):
    """Set up all required application directories"""
    directories = [
        app.config.get('UPLOAD_FOLDER', '/app/data/uploads'),
        'static/css',
        'static/js',
        'templates',
        os.path.dirname(app.config.get('DATABASE_PATH', '/app/data/malware_platform.db'))
    ]
    
    for directory in directories:
        os.makedirs(directory, exist_ok=True)

def _load_modules(app):
    """Dynamically load and initialize all modules"""
    logger = logging.getLogger(__name__)
    
    for module_name, module_path in MODULES.items():
        try:
            # Dynamically import the module
            module = importlib.import_module(module_path)
            
            # Initialize the module
            if hasattr(module, 'init_app'):
                module.init_app(app)
                logger.info(f"Initialized module: {module_name}")
            else:
                logger.warning(f"Module {module_name} has no init_app method")
                
        except ImportError as e:
            logger.error(f"Failed to import module {module_name}: {str(e)}")
        except Exception as e:
            logger.error(f"Error initializing module {module_name}: {str(e)}")

def _init_database():
    """Initialize the database with schema from all modules"""
    db_path = current_app.config.get('DATABASE_PATH', '/app/data/malware_platform.db')
    logger = logging.getLogger(__name__)
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    try:
        # Create database connection
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Initialize schemas from all modules
        for module_name, module_path in MODULES.items():
            try:
                module = importlib.import_module(module_path)
                
                if hasattr(module, 'create_database_schema'):
                    module.create_database_schema(cursor)
                    logger.info(f"Created database schema for {module_name}")
                else:
                    logger.info(f"Module {module_name} has no database schema")
            except Exception as e:
                logger.error(f"Error creating schema for {module_name}: {str(e)}")
        
        # Commit changes and close
        conn.commit()
        conn.close()
        logger.info("Database initialization complete")
        
    except Exception as e:
        logger.error(f"Database initialization failed: {str(e)}")
        raise

def create_cli_commands(app):
    """Register CLI commands for the application"""
    @app.cli.command("init-db")
    def init_db_command():
        """Initialize the database."""
        with app.app_context():
            _init_database()
        print("Initialized the database.")
    
    @app.cli.command("create-buckets")
    def create_buckets_command():
        """Create GCP storage buckets if they don't exist."""
        from google.cloud import storage
        
        client = storage.Client()
        
        # Create malware samples bucket
        samples_bucket_name = app.config.get('GCP_STORAGE_BUCKET')
        try:
            if not client.bucket(samples_bucket_name).exists():
                bucket = client.create_bucket(samples_bucket_name)
                print(f"Created bucket {bucket.name}")
            else:
                print(f"Bucket {samples_bucket_name} already exists")
        except Exception as e:
            print(f"Error creating samples bucket: {str(e)}")
            
        # Create results bucket
        results_bucket_name = app.config.get('GCP_RESULTS_BUCKET')
        try:
            if not client.bucket(results_bucket_name).exists():
                bucket = client.create_bucket(results_bucket_name)
                print(f"Created bucket {bucket.name}")
            else:
                print(f"Bucket {results_bucket_name} already exists")
        except Exception as e:
            print(f"Error creating results bucket: {str(e)}")

if __name__ == "__main__":
    app = create_app()
    create_cli_commands(app)
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=app.config.get('DEBUG', False))
