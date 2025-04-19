from flask import Flask, render_template, jsonify, g, request, redirect, url_for
import os
import logging
import importlib
import time
import sys
import traceback
from pathlib import Path

# Configure logging with more detailed format
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Core module configuration
MODULES = {
    'web': 'web_interface',
    'malware': 'malware_module',
    'detonation': 'detonation_module',
    'viz': 'viz_module'
}

# CRITICAL: Module initialization order - web module MUST be first to handle the root route
MODULE_INIT_ORDER = ['web', 'malware', 'detonation', 'viz']

# Track module initialization status
module_status = {name: {'initialized': False, 'error': None} for name in MODULES}

def get_module(module_name):
    """Get module by name, for inter-module communication."""
    if module_name not in MODULES:
        return None
        
    try:
        # Check if module is already imported
        module_path = MODULES[module_name]
        if module_path in sys.modules:
            return sys.modules[module_path]
            
        # Import the module
        module = importlib.import_module(module_path)
        return module
    except Exception as e:
        logger.error(f"Error importing module {module_name}: {e}")
        module_status[module_name]['error'] = str(e)
        return None

def handle_not_found(e):
    """Handle 404 errors gracefully"""
    logger.warning(f"404 error: {request.path} not found")
    try:
        return render_template('error.html', 
                              error_code=404,
                              error_message="The requested page was not found."), 404
    except Exception as template_error:
        logger.error(f"Error rendering 404 template: {template_error}")
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Not Found</title>
            <style>
                body {{ font-family: Arial, sans-serif; text-align: center; margin-top: 50px; }}
                h1 {{ color: #dc3545; }}
                a {{ color: #4a6fa5; text-decoration: none; }}
                a:hover {{ text-decoration: underline; }}
            </style>
        </head>
        <body>
            <h1>404 - Page Not Found</h1>
            <p>The requested URL {request.path} was not found on this server.</p>
            <p><a href="/">Return to Home</a></p>
        </body>
        </html>
        """, 404

def ensure_directories():
    """Ensure all required directories exist."""
    required_dirs = [
        'templates', 
        'static',
        'static/css',
        'static/js', 
        'data',
        'data/uploads',
        'data/database',
        'logs'
    ]
    
    for directory in required_dirs:
        # Make sure to use correct absolute paths
        if not os.path.isabs(directory):
            directory = os.path.join(os.getcwd(), directory)
        
        try:
            os.makedirs(directory, exist_ok=True)
            logger.info(f"Ensured directory exists: {directory}")
        except Exception as e:
            logger.error(f"Error creating directory {directory}: {e}")

def ensure_base_templates():
    """Ensure base templates exist."""
    from web_interface import generate_base_templates
    
    try:
        generate_base_templates()
        logger.info("Base templates have been created or verified")
    except Exception as e:
        logger.error(f"Error generating base templates: {e}")
        
        # Fallback - create minimal templates directly
        templates_dir = os.path.join(os.getcwd(), 'templates')
        os.makedirs(templates_dir, exist_ok=True)
        
        # Create minimal base.html
        with open(os.path.join(templates_dir, 'base.html'), 'w') as f:
            f.write("""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{% block title %}Malware Detonation Platform{% endblock %}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-primary">
        <div class="container">
            <a class="navbar-brand" href="/">Malware Detonation Platform</a>
        </div>
    </nav>
    <div class="container mt-4">
        {% block content %}{% endblock %}
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>""")
        
        # Create minimal index.html
        with open(os.path.join(templates_dir, 'index.html'), 'w') as f:
            f.write("""{% extends 'base.html' %}
{% block content %}
<h1>Malware Detonation Platform</h1>
<p>Welcome to the platform.</p>
<div class="row mt-4">
    <div class="col-md-3">
        <div class="card">
            <div class="card-body">
                <h5 class="card-title">Malware Analysis</h5>
                <a href="/malware" class="btn btn-primary">Go</a>
            </div>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card">
            <div class="card-body">
                <h5 class="card-title">Detonation Service</h5>
                <a href="/detonation" class="btn btn-primary">Go</a>
            </div>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card">
            <div class="card-body">
                <h5 class="card-title">Visualizations</h5>
                <a href="/viz" class="btn btn-primary">Go</a>
            </div>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card">
            <div class="card-body">
                <h5 class="card-title">Diagnostics</h5>
                <a href="/diagnostic" class="btn btn-primary">Go</a>
            </div>
        </div>
    </div>
</div>
{% endblock %}""")
        
        # Create minimal error.html
        with open(os.path.join(templates_dir, 'error.html'), 'w') as f:
            f.write("""{% extends 'base.html' %}
{% block content %}
<div class="alert alert-danger">
    <h1>Error {{ error_code }}</h1>
    <p>{{ error_message }}</p>
</div>
<a href="/" class="btn btn-primary">Return to Home</a>
{% endblock %}""")
        
        logger.info("Created minimal fallback templates")

def initialize_database(app):
    """Initialize the database."""
    try:
        with app.app_context():
            from database import init_app as init_db
            init_db(app)
            logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        logger.warning("Application will start but database functionality may be limited")

def create_app(test_config=None):
    """Create and configure the Flask application with robust error handling and fallbacks."""
    # Record start time for uptime tracking
    start_time = time.time()
    
    try:
        # Create Flask app with explicit template and static folders
        app = Flask(__name__, 
                    static_folder='static',
                    template_folder='templates')
        
        # Explicitly set the paths to avoid any path resolution issues
        app.root_path = os.path.dirname(os.path.abspath(__file__))
        app.static_folder = os.path.join(app.root_path, 'static')
        app.template_folder = os.path.join(app.root_path, 'templates')
        
        # Ensure required directories exist
        ensure_directories()
        
        # Load configuration
        app.config.update({
            'DATABASE_PATH': os.environ.get('DATABASE_PATH', os.path.join(app.root_path, 'data', 'malware_platform.db')),
            'UPLOAD_FOLDER': os.environ.get('UPLOAD_FOLDER', os.path.join(app.root_path, 'data', 'uploads')),
            'MAX_UPLOAD_SIZE_MB': int(os.environ.get('MAX_UPLOAD_SIZE_MB', 100)),
            'DEBUG': os.environ.get('DEBUG', 'False').lower() in ('true', '1', 't'),
            'APP_NAME': os.environ.get('APP_NAME', "Malware Detonation Platform"),
            'GENERATE_TEMPLATES': os.environ.get('GENERATE_TEMPLATES', 'True').lower() in ('true', '1', 't'),
            'INITIALIZE_GCP': os.environ.get('INITIALIZE_GCP', 'False').lower() in ('true', '1', 't'),
            'SKIP_DB_INIT': os.environ.get('SKIP_DB_INIT', 'False').lower() in ('true', '1', 't'),
            'START_TIME': start_time,
            # Add critical for login
            'SECRET_KEY': os.environ.get('SECRET_KEY', os.urandom(24).hex())
        })
        
        # Set MAX_CONTENT_LENGTH based on MAX_UPLOAD_SIZE_MB
        app.config['MAX_CONTENT_LENGTH'] = app.config['MAX_UPLOAD_SIZE_MB'] * 1024 * 1024
        
        # Register error handlers
        app.register_error_handler(404, handle_not_found)
        logger.info("Registered 404 error handler")
        
        # Ensure basic templates exist before anything else
        ensure_base_templates()
        
        # Initialize database early to ensure it exists
        initialize_database(app)
        
        # Set up request tracking for performance monitoring
        @app.before_request
        def before_request():
            g.start_time = time.time()
            
        @app.after_request
        def after_request(response):
            if hasattr(g, 'start_time'):
                duration = time.time() - g.start_time
                response.headers['X-Request-Duration'] = str(duration)
            return response
        
        # Register health check endpoint
        @app.route('/health')
        def health_check():
            # Get database health if possible
            db_health = {"status": "unknown"}
            try:
                # Import function if available
                from database import check_database_health
                db_health = check_database_health()
            except ImportError:
                # Basic check if not available
                try:
                    from database import get_db_connection
                    conn = get_db_connection()
                    conn.execute("SELECT 1")
                    conn.close()
                    db_health = {"status": "healthy"}
                except Exception as e:
                    db_health = {"status": "unhealthy", "error": str(e)}
            
            # Build comprehensive health data
            health_data = {
                "status": "healthy",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "uptime_seconds": int(time.time() - app.config.get('START_TIME', 0)),
                "components": {
                    "database": db_health,
                    "modules": module_status
                }
            }
            
            # Determine overall health status
            if db_health.get("status") != "healthy":
                health_data["status"] = "degraded"
                
            for module, status in module_status.items():
                if not status.get("initialized", False):
                    health_data["status"] = "degraded"
                    break
            
            return jsonify(health_data)
        
        # CRITICAL CHANGE: Initialize modules in the defined order, with web module first
        # This ensures the web blueprint handles the root route properly
        with app.app_context():
            for module_name in MODULE_INIT_ORDER:
                try:
                    module = get_module(module_name)
                    if module and hasattr(module, 'init_app'):
                        logger.info(f"Initializing module: {module_name}")
                        module.init_app(app)
                        module_status[module_name]['initialized'] = True
                        logger.info(f"Successfully initialized module: {module_name}")
                    else:
                        logger.warning(f"Module {module_name} has no init_app function or could not be imported")
                except Exception as e:
                    logger.error(f"Error initializing module {module_name}: {e}")
                    module_status[module_name]['error'] = str(e)
                    logger.warning(f"Module {module_name} will not be available")
        
        # Add alternate routes for the root path to handle edge cases
        @app.route('/index')
        @app.route('/home')
        @app.route('/start')
        def redirect_to_root():
            logger.info("Redirecting alternate root URLs to /")
            return redirect(url_for('web.index'))
        
        # Diagnostic route for debugging
        @app.route('/debug-info')
        def debug_info():
            """Endpoint for debugging template and module issues"""
            return jsonify({
                'app_config': {k: str(v) for k, v in app.config.items() if k != 'SECRET_KEY'},
                'template_dir': app.template_folder,
                'static_dir': app.static_folder,
                'template_dir_exists': os.path.exists(app.template_folder),
                'static_dir_exists': os.path.exists(app.static_folder),
                'template_files': os.listdir(app.template_folder) if os.path.exists(app.template_folder) else [],
                'static_files': os.listdir(app.static_folder) if os.path.exists(app.static_folder) else [],
                'module_status': module_status,
                'database_path': app.config.get('DATABASE_PATH'),
                'database_exists': os.path.exists(app.config.get('DATABASE_PATH'))
            })
        
        # Mark application as ready
        try:
            from app_ready import mark_app_ready
            mark_app_ready()
            logger.info("Application marked as ready")
        except Exception as e:
            logger.warning(f"Could not mark application as ready: {e}")
        
        logger.info(f"Application startup completed in {time.time() - start_time:.2f} seconds")
        return app
    except Exception as e:
        # Catastrophic failure - create minimal emergency app
        error_details = traceback.format_exc()
        logger.critical(f"CRITICAL ERROR during app creation: {e}\n{error_details}")
        
        # Create a simplified fallback emergency application
        emergency_app = Flask(__name__)
        
        @emergency_app.route('/')
        def emergency_home():
            return f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Malware Detonation Platform - Emergency Mode</title>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 40px; }}
                    h1 {{ color: #dc3545; }}
                    .error-card {{ background: #f8d7da; padding: 20px; border-radius: 8px; margin-top: 20px; }}
                    .links {{ margin-top: 30px; }}
                    .links a {{ display: inline-block; margin: 5px; padding: 8px 16px; color: white; 
                              background-color: #4a6fa5; text-decoration: none; border-radius: 4px; }}
                    pre {{ background: #f8f9fa; padding: 15px; border-radius: 5px; overflow: auto; max-height: 300px; }}
                </style>
            </head>
            <body>
                <h1>Malware Detonation Platform - Emergency Mode</h1>
                <p>The application is running in emergency mode due to critical initialization errors.</p>
                
                <div class="error-card">
                    <h2>Error Details</h2>
                    <p>{str(e)}</p>
                    <pre>{error_details}</pre>
                </div>
                
                <div class="links">
                    <p>The following links may not work properly:</p>
                    <a href="/malware">Malware Analysis</a>
                    <a href="/detonation">Detonation Service</a>
                    <a href="/viz">Visualizations</a>
                    <a href="/health">Health Check</a>
                    <a href="/debug-info">Debug Info</a>
                </div>
            </body>
            </html>
            """
            
        @emergency_app.route('/health')
        def emergency_health():
            return jsonify({
                "status": "critical",
                "error": str(e),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }), 500
            
        @emergency_app.route('/debug-info')
        def emergency_debug():
            return jsonify({
                "error": str(e),
                "traceback": error_details,
                "cwd": os.getcwd(),
                "files": os.listdir('.'),
                "env": {k: v for k, v in os.environ.items() if 'KEY' not in k.upper()}
            })
        
        logger.info("Emergency application created as fallback")
        return emergency_app

if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=app.config.get('DEBUG', False))
