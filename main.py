from flask import Flask, current_app
import os
import sqlite3
import logging
import importlib
from pathlib import Path
from google.cloud import logging as gcp_logging

# Module configuration
MODULES = {
    'malware': 'malware_module',  # Handles malware samples (replaces data_module)
    'detonation': 'detonation_module',  # Handles VM detonation (replaces analysis_module)
    'results': 'results_module',  # Handles analysis results (replaces viz_module)
    'web': 'web_interface_module'  # Web interface remains the same
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
        raise
    
    # Setup required directories 
    _setup_directories(app)
    
    # Initialize database
    with app.app_context():
        _init_database()
    
    # Load and register all modules dynamically
    _load_modules(app)
    
    # Register error handlers
    @app.errorhandler(404)
    def page_not_found(e):
        mod = importlib.import_module(MODULES['web'])
        return mod.handle_404(), 404

    @app.errorhandler(500)
    def server_error(e):
        mod = importlib.import_module(MODULES['web'])
        return mod.handle_500(), 500
        
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
        app.config['UPLOAD_FOLDER'],
        'static/css',
        'static/js',
        'templates',
        os.path.dirname(app.config['DATABASE_PATH'])
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
            raise
        except Exception as e:
            logger.error(f"Error initializing module {module_name}: {str(e)}")
            raise

def _init_database():
    """Initialize the database with schema from all modules"""
    db_path = current_app.config['DATABASE_PATH']
    logger = logging.getLogger(__name__)
    
    try:
        # Create database connection
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Initialize schemas from all modules
        for module_name, module_path in MODULES.items():
            module = importlib.import_module(module_path)
            
            if hasattr(module, 'create_database_schema'):
                module.create_database_schema(cursor)
                logger.info(f"Created database schema for {module_name}")
            else:
                logger.info(f"Module {module_name} has no database schema")
        
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
        samples_bucket_name = app.config['GCP_STORAGE_BUCKET']
        if not client.bucket(samples_bucket_name).exists():
            bucket = client.create_bucket(samples_bucket_name)
            print(f"Created bucket {bucket.name}")
        else:
            print(f"Bucket {samples_bucket_name} already exists")
            
        # Create results bucket
        results_bucket_name = app.config['GCP_RESULTS_BUCKET']
        if not client.bucket(results_bucket_name).exists():
            bucket = client.create_bucket(results_bucket_name)
            print(f"Created bucket {bucket.name}")
        else:
            print(f"Bucket {results_bucket_name} already exists")

if __name__ == "__main__":
    app = create_app()
    create_cli_commands(app)
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=app.config['DEBUG'])
