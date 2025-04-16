from flask import Flask, current_app
import os
import sqlite3
import logging
from google.cloud import logging as gcp_logging

# Global registry for lazy-loaded modules
_loaded_modules = {}

# Module configuration
MODULES = {
    'malware': 'malware_module',
    'detonation': 'detonation_module',
    'viz': 'viz_module',
    'web': 'web_interface'
}

def create_app(test_config=None):
    """Application factory with optimized loading to reduce memory usage"""
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
        
        # Configure templates to be pre-generated during build, not runtime
        app.config['GENERATE_TEMPLATES'] = False
        
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
            GENERATE_TEMPLATES=False
        )
    
    # Setup required directories - only essential ones at startup
    _setup_essential_directories(app)
    
    # Initialize database schema - but don't load all data
    with app.app_context():
        try:
            _init_database_schema()
        except Exception as e:
            logger.error(f"Database initialization error: {str(e)}")
    
    # Initialize only critical modules immediately (like 'web')
    # Other modules will be lazy-loaded when needed
    _init_core_modules(app)
    
    # Register error handlers
    @app.errorhandler(404)
    def page_not_found(e):
        # Lazy load web module only when needed
        web_module = get_module('web')
        if hasattr(web_module, 'handle_404'):
            return web_module.handle_404(), 404
        return "Page not found", 404

    @app.errorhandler(500)
    def server_error(e):
        # Lazy load web module only when needed
        web_module = get_module('web')
        if hasattr(web_module, 'handle_500'):
            return web_module.handle_500(), 500
        return "Server error", 500
        
    # Add health check endpoint for Cloud Run
    @app.route('/health')
    def health_check():
        return {'status': 'healthy'}, 200
    
    # Register Blueprint lazy-loading routes
    _register_lazy_routes(app)
    
    logger.info("Application setup complete")
    return app

def get_module(module_name):
    """Lazy-load a module only when needed"""
    if module_name not in _loaded_modules:
        import importlib
        if module_name in MODULES:
            try:
                _loaded_modules[module_name] = importlib.import_module(MODULES[module_name])
                logging.getLogger(__name__).info(f"Lazy-loaded module: {module_name}")
            except ImportError as e:
                logging.getLogger(__name__).error(f"Failed to import module {module_name}: {str(e)}")
                return None
    return _loaded_modules.get(module_name)

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

def _setup_essential_directories(app):
    """Set up only essential directories at startup"""
    # Only create critical directories at startup
    essential_dirs = [
        app.config.get('UPLOAD_FOLDER', '/app/data/uploads'),
        'static',
        'templates',
        os.path.dirname(app.config.get('DATABASE_PATH', '/app/data/malware_platform.db'))
    ]
    
    for directory in essential_dirs:
        os.makedirs(directory, exist_ok=True)

def _init_core_modules(app):
    """Initialize only critical modules (e.g., web interface)"""
    logger = logging.getLogger(__name__)
    
    # Only initialize the web module at startup
    web_module_name = 'web'
    try:
        web_module = get_module(web_module_name)
        if hasattr(web_module, 'init_app'):
            web_module.init_app(app)
            logger.info(f"Initialized core module: {web_module_name}")
    except Exception as e:
        logger.error(f"Error initializing core module {web_module_name}: {str(e)}")

def _register_lazy_routes(app):
    """Register routes that trigger lazy module loading"""
    logger = logging.getLogger(__name__)
    
    # Register malware routes
    @app.route('/malware', defaults={'path': ''})
    @app.route('/malware/<path:path>')
    def malware_routes(path):
        malware_module = get_module('malware')
        if not hasattr(malware_module, 'malware_bp'):
            logger.error("Malware module not properly loaded")
            return "Module error", 500
            
        # Register blueprint if not already registered
        if not app.blueprints.get('malware'):
            app.register_blueprint(malware_module.malware_bp)
            
        # Dispatch to the module
        return app.dispatch_request()
    
    # Register detonation routes
    @app.route('/detonation', defaults={'path': ''})
    @app.route('/detonation/<path:path>')
    def detonation_routes(path):
        detonation_module = get_module('detonation')
        if not hasattr(detonation_module, 'detonation_bp'):
            logger.error("Detonation module not properly loaded")
            return "Module error", 500
            
        # Register blueprint if not already registered
        if not app.blueprints.get('detonation'):
            app.register_blueprint(detonation_module.detonation_bp)
            
        # Dispatch to the module
        return app.dispatch_request()
    
    # Register visualization routes
    @app.route('/viz', defaults={'path': ''})
    @app.route('/viz/<path:path>')
    def viz_routes(path):
        viz_module = get_module('viz')
        if not hasattr(viz_module, 'viz_bp'):
            logger.error("Visualization module not properly loaded")
            return "Module error", 500
            
        # Register blueprint if not already registered
        if not app.blueprints.get('viz'):
            app.register_blueprint(viz_module.viz_bp)
            
        # Dispatch to the module
        return app.dispatch_request()

def _init_database_schema():
    """Initialize the database schema only, without loading data"""
    db_path = current_app.config.get('DATABASE_PATH', '/app/data/malware_platform.db')
    logger = logging.getLogger(__name__)
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    # Use context manager for proper cleanup
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            
            # Create minimal web interface schema first
            web_module = get_module('web')
            if hasattr(web_module, 'create_database_schema'):
                web_module.create_database_schema(cursor)
                logger.info("Created web interface database schema")
            
            # Commit changes to ensure core functionality works
            conn.commit()
        
        logger.info("Core database initialization complete")
        
    except Exception as e:
        logger.error(f"Database initialization failed: {str(e)}")
        raise

if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=app.config.get('DEBUG', False))
