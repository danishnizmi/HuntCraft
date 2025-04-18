from flask import Flask, current_app, request, render_template, jsonify, g
import os
import sqlite3
import logging
import importlib
import threading
import time
import sys
import traceback
from pathlib import Path
from datetime import datetime
import json

# Configure logging format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Module configuration - core system modules
MODULES = {
    'web': 'web_interface',
    'malware': 'malware_module',
    'detonation': 'detonation_module',
    'viz': 'viz_module'
}

# Module initialization order - ensures dependencies are loaded properly
MODULE_INIT_ORDER = ['web', 'malware', 'detonation', 'viz']

# Track module initialization status
module_status = {name: {'initialized': False, 'error': None} for name in MODULES}

def get_module(module_name):
    """Get module by name, for inter-module communication.
    
    Args:
        module_name (str): Name of the module to import
        
    Returns:
        module: Imported module or None if not found/loadable
    """
    if module_name not in MODULES:
        logger.warning(f"Requested unknown module: {module_name}")
        return None
        
    try:
        # Check if module is already imported
        if module_name in sys.modules:
            return sys.modules[MODULES[module_name]]
            
        # Import the module
        module = importlib.import_module(MODULES[module_name])
        return module
    except ImportError as e:
        logger.error(f"Error importing module {module_name}: {str(e)}")
        module_status[module_name]['error'] = str(e)
        return None
    except Exception as e:
        logger.error(f"Unexpected error importing module {module_name}: {str(e)}")
        module_status[module_name]['error'] = str(e)
        return None

def initialize_module(app, module_name, critical=False):
    """Initialize a specific module with proper error handling.
    
    Args:
        app: Flask application
        module_name (str): Name of the module to initialize
        critical (bool): Whether this module is critical for application function
        
    Returns:
        bool: True if initialization succeeded, False otherwise
    """
    try:
        if module_status[module_name]['initialized']:
            logger.info(f"Module {module_name} already initialized, skipping")
            return True
            
        module = get_module(module_name)
        if not module:
            logger.error(f"Failed to import module {module_name}")
            if critical:
                raise ImportError(f"Critical module {module_name} could not be imported")
            return False
        
        # Initialize the module if it has an init_app function
        if hasattr(module, 'init_app'):
            logger.info(f"Initializing module: {module_name}")
            module.init_app(app)
            module_status[module_name]['initialized'] = True
            logger.info(f"Successfully initialized module: {module_name}")
            return True
        else:
            logger.warning(f"Module {module_name} has no init_app function")
            module_status[module_name]['initialized'] = True  # Mark as initialized anyway
            return True
            
    except Exception as e:
        error_details = traceback.format_exc()
        logger.error(f"Error initializing module {module_name}: {str(e)}\n{error_details}")
        module_status[module_name]['error'] = str(e)
        
        if critical:
            raise
        return False

def load_config(app, test_config=None):
    """Load application configuration from various sources.
    
    Args:
        app: Flask application
        test_config: Test configuration to use instead of normal config
        
    Returns:
        dict: The loaded configuration
    """
    config_data = {}
    
    try:
        # 1. First try to load from config.py
        try:
            import config
            app.config.from_object(config.Config if not test_config else test_config)
            logger.info("Configuration loaded from config.py")
            config_data = {key: value for key, value in app.config.items() 
                          if not key.startswith('_')}
        except ImportError:
            logger.warning("config.py not found, using environment variables")
        except Exception as e:
            logger.error(f"Error loading configuration from config.py: {str(e)}")
        
        # 2. Override with environment variables
        env_vars = {
            'SECRET_KEY': os.environ.get('SECRET_KEY', 'dev-key'),
            'DATABASE_PATH': os.environ.get('DATABASE_PATH', '/app/data/malware_platform.db'),
            'UPLOAD_FOLDER': os.environ.get('UPLOAD_FOLDER', '/app/data/uploads'),
            'MAX_UPLOAD_SIZE_MB': int(os.environ.get('MAX_UPLOAD_SIZE_MB', 100)),
            'DEBUG': os.environ.get('DEBUG', 'False').lower() in ('true', '1', 't'),
            'APP_NAME': os.environ.get('APP_NAME', "Malware Detonation Platform"),
            'GCP_PROJECT_ID': os.environ.get('GCP_PROJECT_ID', ''),
            'GCP_REGION': os.environ.get('GCP_REGION', 'us-central1'),
            'GCP_ZONE': os.environ.get('GCP_ZONE', 'us-central1-a'),
            'PRIMARY_COLOR': os.environ.get('PRIMARY_COLOR', '#4a6fa5'),
            'SECONDARY_COLOR': os.environ.get('SECONDARY_COLOR', '#6c757d'),
            'DANGER_COLOR': os.environ.get('DANGER_COLOR', '#dc3545'),
            'SUCCESS_COLOR': os.environ.get('SUCCESS_COLOR', '#28a745'),
            'WARNING_COLOR': os.environ.get('WARNING_COLOR', '#ffc107'),
            'INFO_COLOR': os.environ.get('INFO_COLOR', '#17a2b8'),
            'DARK_COLOR': os.environ.get('DARK_COLOR', '#343a40'),
            'LIGHT_COLOR': os.environ.get('LIGHT_COLOR', '#f8f9fa'),
            'ENABLE_ADVANCED_ANALYSIS': os.environ.get('ENABLE_ADVANCED_ANALYSIS', 'True').lower() in ('true', '1', 't'),
            'ENABLE_DATA_EXPORT': os.environ.get('ENABLE_DATA_EXPORT', 'True').lower() in ('true', '1', 't'),
            'ENABLE_VISUALIZATION': os.environ.get('ENABLE_VISUALIZATION', 'True').lower() in ('true', '1', 't'),
            'GENERATE_TEMPLATES': os.environ.get('GENERATE_TEMPLATES', 'False').lower() in ('true', '1', 't'),
            'INITIALIZE_GCP': os.environ.get('INITIALIZE_GCP', 'False').lower() in ('true', '1', 't'),
            'SKIP_DB_INIT': os.environ.get('SKIP_DB_INIT', 'False').lower() in ('true', '1', 't'),
            'GCP_STORAGE_BUCKET': os.environ.get('GCP_STORAGE_BUCKET', ''),
            'GCP_RESULTS_BUCKET': os.environ.get('GCP_RESULTS_BUCKET', ''),
            'ON_CLOUD_RUN': os.environ.get('K_SERVICE') is not None
        }
        
        # Update app config with environment variables
        app.config.update(env_vars)
        
        # Update config_data with env vars for return value
        config_data.update(env_vars)
        
        # 3. Set MAX_CONTENT_LENGTH based on MAX_UPLOAD_SIZE_MB
        app.config['MAX_CONTENT_LENGTH'] = app.config['MAX_UPLOAD_SIZE_MB'] * 1024 * 1024
        config_data['MAX_CONTENT_LENGTH'] = app.config['MAX_CONTENT_LENGTH']
        
        logger.info(f"Configuration loaded successfully with {len(config_data)} settings")
        return config_data
        
    except Exception as e:
        logger.error(f"Error in configuration loading: {str(e)}")
        # Return at least basic configuration to allow app to start
        return config_data

def setup_essential_directories(app):
    """Create essential directories for application function.
    
    Args:
        app: Flask application
    """
    directories = [
        app.config.get('UPLOAD_FOLDER', '/app/data/uploads'),
        'static/css',
        'static/js',
        'templates',
        os.path.dirname(app.config.get('DATABASE_PATH', '/app/data/malware_platform.db'))
    ]
    
    for directory in directories:
        try:
            os.makedirs(directory, exist_ok=True)
            logger.debug(f"Ensured directory exists: {directory}")
        except Exception as e:
            logger.error(f"Error creating directory {directory}: {str(e)}")
            # Continue with other directories even if one fails

def ensure_index_template(app):
    """Create a minimal index.html if it doesn't exist.
    
    Args:
        app: Flask application
    """
    try:
        template_dir = app.template_folder
        
        # Make sure the path is absolute
        if not os.path.isabs(template_dir):
            template_dir = os.path.join(app.root_path, template_dir)
            
        logger.info(f"Ensuring templates exist in directory: {template_dir}")
        
        # Ensure directories exist
        os.makedirs(template_dir, exist_ok=True)
        
        # First ensure base.html exists
        base_path = os.path.join(template_dir, 'base.html')
        if not os.path.exists(base_path):
            logger.info(f"Base template doesn't exist, creating it at: {base_path}")
            with open(base_path, 'w') as f:
                f.write("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}{{ app_name }}{% endblock %}</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; text-align: center; }
        h1 { color: #4a6fa5; }
        .card { background: #f8f9fa; border-radius: 8px; padding: 20px; margin-top: 20px; }
        a { color: #4a6fa5; text-decoration: none; }
        a:hover { text-decoration: underline; }
    </style>
    {% block head %}{% endblock %}
</head>
<body>
    <h1>{% block header %}{{ app_name }}{% endblock %}</h1>
    {% block content %}{% endblock %}
</body>
</html>""")
            logger.info("Created base.html template")
        
        # Now create index.html
        index_path = os.path.join(template_dir, 'index.html')
        if not os.path.exists(index_path):
            logger.info(f"Index template doesn't exist, creating it at: {index_path}")
            with open(index_path, 'w') as f:
                f.write("""{% extends 'base.html' %}

{% block title %}{{ app_name }}{% endblock %}

{% block content %}
    <div class="card">
        <p>The application is running. Use the links below to navigate:</p>
        <ul style="list-style:none; padding:0;">
            <li><a href="/malware">Malware Analysis</a></li>
            <li><a href="/detonation">Detonation Service</a></li>
            <li><a href="/viz">Visualizations</a></li>
        </ul>
    </div>
{% endblock %}""")
            logger.info("Created index.html template")
            
        # Verify templates are readable
        try:
            with open(base_path, 'r') as f:
                base_content = f.read()
                logger.info(f"Successfully verified base.html is readable ({len(base_content)} bytes)")
                
            with open(index_path, 'r') as f:
                index_content = f.read()
                logger.info(f"Successfully verified index.html is readable ({len(index_content)} bytes)")
        except Exception as verify_error:
            logger.error(f"Failed to verify templates are readable: {str(verify_error)}")
            
        # List all templates for debugging
        try:
            templates = os.listdir(template_dir)
            logger.info(f"Templates directory contains: {templates}")
        except Exception as list_error:
            logger.error(f"Failed to list templates directory: {str(list_error)}")
    except Exception as e:
        logger.error(f"Error creating index template: {str(e)}")
        # Continue execution to allow fallback templates

def register_app_routes(app):
    """Register direct routes on the app for critical paths.
    
    Args:
        app: Flask application
    """
    @app.route('/')
    def root():
        """Direct root route handler."""
        logger.info("Direct app root route handler called")
        try:
            return render_template('index.html')
        except Exception as e:
            error_details = traceback.format_exc()
            logger.error(f"Error rendering index from direct route: {e}\n{error_details}")
            
            # Return a simple HTML response
            return f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Malware Detonation Platform</title>
                <style>
                    body {{ font-family: Arial, sans-serif; text-align: center; margin-top: 50px; }}
                    h1 {{ color: #4a6fa5; }}
                    .links {{ margin-top: 20px; }}
                    .links a {{ display: inline-block; margin: 0 10px; color: #4a6fa5; text-decoration: none; }}
                    .links a:hover {{ text-decoration: underline; }}
                </style>
            </head>
            <body>
                <h1>Malware Detonation Platform</h1>
                <p>Welcome to the Malware Detonation Platform.</p>
                <div class="links">
                    <a href="/malware">Malware Analysis</a>
                    <a href="/detonation">Detonation Service</a>
                    <a href="/viz">Visualizations</a>
                    <a href="/diagnostic">System Diagnostics</a>
                </div>
            </body>
            </html>
            """
    
    @app.route('/diagnostic')
    def app_diagnostic():
        """Diagnostic info about the app."""
        try:
            # Get module info
            module_info = {name: {'initialized': status.get('initialized', False)} 
                          for name, status in module_status.items()}
            
            # Get template info
            template_dir = app.template_folder
            if not os.path.isabs(template_dir):
                template_dir = os.path.join(app.root_path, template_dir)
                
            template_info = {
                'path': template_dir,
                'exists': os.path.exists(template_dir)
            }
            
            if template_info['exists']:
                template_info['files'] = os.listdir(template_dir)
            
            # Get blueprint info
            blueprint_info = [{'name': bp.name, 'url_prefix': bp.url_prefix} 
                             for bp in app.blueprints.values()]
            
            # Get route info
            route_info = []
            for rule in app.url_map.iter_rules():
                route_info.append({
                    'endpoint': rule.endpoint,
                    'methods': list(rule.methods),
                    'path': str(rule)
                })
            
            # Prepare diagnostic data
            diagnostic = {
                'app_name': app.name,
                'debug': app.debug,
                'modules': module_info,
                'blueprints': blueprint_info,
                'templates': template_info,
                'routes': route_info,
                'time': datetime.now().isoformat()
            }
            
            # Return as JSON
            return jsonify(diagnostic)
        except Exception as e:
            logger.error(f"Error in diagnostic route: {e}")
            return jsonify({
                'error': str(e),
                'traceback': traceback.format_exc()
            }), 500

def register_error_handlers(app):
    """Register Flask error handlers for common errors.
    
    Args:
        app: Flask application
    """
    @app.errorhandler(404)
    def page_not_found(e):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Not Found', 'message': str(e)}), 404
        return render_template('error.html', 
                              error_code=404,
                              error_message=f"Page not found: {str(e)}"), 404

    @app.errorhandler(500)
    def server_error(e):
        error_details = traceback.format_exc() if app.config.get('DEBUG', False) else None
        logger.error(f"Server error: {str(e)}\n{error_details}")
        
        if request.path.startswith('/api/'):
            return jsonify({
                'error': 'Internal Server Error', 
                'message': str(e),
                'details': error_details if app.config.get('DEBUG', False) else None
            }), 500
        return render_template('error.html', 
                              error_code=500,
                              error_message=f"Server error: {str(e)}",
                              error_details=error_details), 500
        
    @app.errorhandler(Exception)
    def handle_exception(e):
        error_details = traceback.format_exc()
        logger.error(f"Unhandled exception: {str(e)}\n{error_details}")
        
        if request.path.startswith('/api/'):
            return jsonify({
                'error': 'Unhandled Exception', 
                'message': str(e),
                'details': error_details if app.config.get('DEBUG', False) else None
            }), 500
        return render_template('error.html', 
                              error_code=500,
                              error_message=f"An unexpected error occurred: {str(e)}",
                              error_details=error_details), 500

def register_health_routes(app):
    """Register health check and diagnostic endpoints.
    
    Args:
        app: Flask application
    """
    @app.route('/health')
    def health_check():
        """Basic health check endpoint."""
        try:
            # Test database connection
            db = sqlite3.connect(app.config.get('DATABASE_PATH'))
            db.cursor().execute('SELECT 1').fetchone()
            db.close()
            
            return jsonify({
                'status': 'healthy',
                'database': 'connected',
                'timestamp': datetime.now().isoformat()
            }), 200
        except Exception as e:
            logger.error(f"Health check failed: {str(e)}")
            return jsonify({
                'status': 'unhealthy',
                'database': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }), 500
    
    @app.route('/health/extended')
    def extended_health_check():
        """Extended health check with detailed status."""
        health_data = {
            'status': 'healthy',
            'components': {
                'database': {'status': 'unknown'},
                'modules': module_status,
                'filesystem': {'status': 'unknown'},
            },
            'config': {
                'debug': app.config.get('DEBUG', False),
                'environment': os.environ.get('FLASK_ENV', 'production'),
                'app_name': app.config.get('APP_NAME', 'Malware Detonation Platform')
            },
            'timestamp': datetime.now().isoformat()
        }
        
        status_code = 200
        
        # Check database
        try:
            db = sqlite3.connect(app.config.get('DATABASE_PATH'))
            db.cursor().execute('SELECT 1').fetchone()
            db.close()
            health_data['components']['database'] = {
                'status': 'healthy',
                'path': app.config.get('DATABASE_PATH')
            }
        except Exception as e:
            health_data['components']['database'] = {
                'status': 'error',
                'error': str(e),
                'path': app.config.get('DATABASE_PATH')
            }
            health_data['status'] = 'degraded'
            status_code = 500
        
        # Check filesystem
        upload_dir = app.config.get('UPLOAD_FOLDER')
        try:
            # Try to write a test file
            test_file = os.path.join(upload_dir, '.healthcheck')
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            
            health_data['components']['filesystem'] = {
                'status': 'healthy',
                'paths': {
                    'upload_folder': upload_dir,
                    'writable': True
                }
            }
        except Exception as e:
            health_data['components']['filesystem'] = {
                'status': 'error',
                'error': str(e),
                'paths': {
                    'upload_folder': upload_dir,
                    'writable': False
                }
            }
            health_data['status'] = 'degraded'
            status_code = 500
            
        # Overall status determination
        if any(component.get('status') == 'error' 
               for component in health_data['components'].values() 
               if isinstance(component, dict)):
            health_data['status'] = 'degraded'
            status_code = 500
            
        return jsonify(health_data), status_code
    
    @app.route('/metrics')
    def metrics():
        """Basic metrics endpoint."""
        try:
            metrics_data = {
                'uptime': time.time() - app.config.get('START_TIME', time.time()),
                'requests': {
                    'total': app.config.get('REQUEST_COUNT', 0),
                    'by_endpoint': app.config.get('ENDPOINT_COUNTS', {})
                },
                'modules': {
                    name: {
                        'initialized': status.get('initialized', False),
                        'status': 'error' if status.get('error') else 'ok'
                    } for name, status in module_status.items()
                },
                'timestamp': datetime.now().isoformat()
            }
            
            return jsonify(metrics_data), 200
        except Exception as e:
            logger.error(f"Error generating metrics: {str(e)}")
            return jsonify({
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }), 500

def check_route_conflicts(app):
    """Check for conflicting routes and report them in logs.
    
    Args:
        app: Flask application
    """
    # Dictionary to track routes by path
    routes_by_path = {}
    
    # Iterate through all routes
    for rule in app.url_map.iter_rules():
        path = str(rule)
        
        # Skip static file routes
        if path.startswith('/static'):
            continue
            
        # Track this route
        if path not in routes_by_path:
            routes_by_path[path] = []
        routes_by_path[path].append(rule.endpoint)
    
    # Check for conflicts
    conflicts = {path: endpoints for path, endpoints in routes_by_path.items() if len(endpoints) > 1}
    
    if conflicts:
        logger.warning(f"Found {len(conflicts)} route conflicts:")
        for path, endpoints in conflicts.items():
            logger.warning(f"  Path '{path}' has multiple endpoints: {', '.join(endpoints)}")
            logger.warning(f"  Flask will use: {endpoints[0]}")
    else:
        logger.info("No route conflicts found.")
    
    # Also log all routes for debugging
    logger.info("Registered routes:")
    for rule in sorted(app.url_map.iter_rules(), key=lambda x: str(x)):
        logger.info(f"  {str(rule)} -> {rule.endpoint}")

def request_middleware(app):
    """Configure middleware for request tracking.
    
    Args:
        app: Flask application
    """
    @app.before_request
    def before_request():
        # Store request start time for performance tracking
        g.start_time = time.time()
        
        # Increment request counter
        app.config['REQUEST_COUNT'] = app.config.get('REQUEST_COUNT', 0) + 1
        
        # Track requests by endpoint for metrics
        endpoint = request.endpoint or 'unknown'
        endpoint_counts = app.config.get('ENDPOINT_COUNTS', {})
        endpoint_counts[endpoint] = endpoint_counts.get(endpoint, 0) + 1
        app.config['ENDPOINT_COUNTS'] = endpoint_counts
    
    @app.after_request
    def after_request(response):
        # Calculate request duration
        if hasattr(g, 'start_time'):
            duration = time.time() - g.start_time
            response.headers['X-Request-Duration'] = str(duration)
            
            # Log slow requests
            if duration > 1.0:  # Log requests that take more than 1 second
                logger.warning(f"Slow request: {request.method} {request.path} took {duration:.2f}s")
        
        # Prevent caching for dynamic content
        if not request.path.startswith('/static/'):
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
            
        return response

def create_app(test_config=None):
    """Application factory to create and configure the Flask app.
    
    Args:
        test_config: Test configuration to use instead of normal config
        
    Returns:
        Flask application instance
    """
    # Record start time for uptime tracking
    start_time = time.time()
    
    # Create Flask app
    app = Flask(__name__, 
                static_folder='static',
                template_folder='templates')
    
    try:
        # Load configuration
        load_config(app, test_config)
        
        # Store application start time
        app.config['START_TIME'] = start_time
        
        # Set up essential directories
        setup_essential_directories(app)
        
        # Ensure basic templates exist FIRST - before any module initialization
        ensure_index_template(app)
        
        # Register direct app routes (not through blueprints)
        register_app_routes(app)
        
        # Register error handlers
        register_error_handlers(app)
        
        # Register health and metrics endpoints
        register_health_routes(app)
        
        # Set up request middleware
        request_middleware(app)
        
        # Initialize database first (always needed)
        try:
            from database import init_app as init_db
            with app.app_context():
                init_db(app)
                logger.info("Database initialization complete")
        except Exception as e:
            logger.error(f"Error initializing database: {str(e)}")
            # Don't re-raise to allow app to start with limited functionality
        
        # Initialize all modules in a defined order
        # This ensures all blueprints are registered before handling requests
        with app.app_context():
            # Process modules in the predefined order
            for module_name in MODULE_INIT_ORDER:
                try:
                    is_critical = module_name == 'web'  # Web module is critical
                    if not module_status[module_name]['initialized']:
                        initialize_module(app, module_name, critical=is_critical)
                except Exception as e:
                    logger.error(f"Error initializing module {module_name}: {str(e)}")
                    if module_name == 'web':  # Only the web module failure should stop app startup
                        raise
            
            # Check for route conflicts
            check_route_conflicts(app)
            
            # Mark application as ready here
            try:
                from app_ready import mark_app_ready
                mark_app_ready()
                logger.info("Application marked as ready")
            except Exception as e:
                logger.warning(f"Could not mark application as ready: {str(e)}")
        
        logger.info(f"Application startup completed in {time.time() - start_time:.2f} seconds")
        return app
        
    except Exception as e:
        error_details = traceback.format_exc()
        logger.critical(f"Error during application initialization: {str(e)}\n{error_details}")
        
        # Create a minimal app that can at least report the error
        if not app.config:
            app.config = {}
        
        @app.route('/')
        def startup_error():
            return f"""
            <html>
                <head><title>Startup Error</title></head>
                <body>
                    <h1>Error during application startup</h1>
                    <p>{str(e)}</p>
                    <pre>{error_details if app.config.get('DEBUG', False) else 'Enable DEBUG mode to see details'}</pre>
                </body>
            </html>
            """, 500
            
        @app.route('/health')
        def health_error():
            return jsonify({
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }), 500
            
        return app

def cli():
    """Command line interface for the application."""
    import click
    
    @click.group()
    def commands():
        """Malware Detonation Platform CLI."""
        pass
    
    @commands.command()
    @click.option('--host', default='0.0.0.0', help='Host to bind to')
    @click.option('--port', default=8080, help='Port to bind to')
    @click.option('--debug/--no-debug', default=False, help='Enable debug mode')
    def run(host, port, debug):
        """Run the application server."""
        os.environ['DEBUG'] = str(debug).lower()
        app = create_app()
        app.run(host=host, port=port, debug=debug)
    
    @commands.command()
    def init_db():
        """Initialize the database schema."""
        click.echo("Initializing database...")
        app = create_app()
        with app.app_context():
            from database import init_db as init_database
            init_database()
        click.echo("Database initialization complete.")
    
    @commands.command()
    @click.option('--all/--no-all', default=False, help='Generate all templates including non-essential ones')
    def generate_templates(all):
        """Generate application templates."""
        click.echo("Generating templates...")
        os.environ['GENERATE_TEMPLATES'] = 'true'
        
        app = create_app()
        with app.app_context():
            # Always ensure index template
            ensure_index_template(app)
            
            if all:
                # Initialize modules to trigger template generation
                for module_name in MODULES:
                    try:
                        module = get_module(module_name)
                        if module and hasattr(module, 'generate_templates'):
                            click.echo(f"Generating templates for {module_name}...")
                            module.generate_templates()
                    except Exception as e:
                        click.echo(f"Error generating templates for {module_name}: {str(e)}")
                        
        click.echo("Template generation complete.")
    
    return commands()

if __name__ == "__main__":
    # When run directly, use the CLI
    cli_app = cli()
    cli_app()
else:
    # When imported, prepare for WSGI
    app = create_app()

# Mark application as ready when fully initialized
try:
    from app_ready import mark_app_ready
    mark_app_ready()
except Exception:
    pass
