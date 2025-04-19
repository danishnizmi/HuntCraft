from flask import Flask, render_template, jsonify, g, request, redirect, url_for, flash
import os
import logging
import importlib
import time
import sys
import traceback
from pathlib import Path
import json
from flask_login import LoginManager, current_user, login_required

# Configure logging with more detailed format
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Core module configuration - central module registry
# Format: {'module_name': {'path': 'module_path', 'initialized': False, 'error': None}}
# This allows for better dynamic loading and status tracking
MODULES = {
    'web': {'path': 'web_interface', 'initialized': False, 'error': None, 'required': True},
    'malware': {'path': 'malware_module', 'initialized': False, 'error': None, 'required': False},
    'detonation': {'path': 'detonation_module', 'initialized': False, 'error': None, 'required': False},
    'viz': {'path': 'viz_module', 'initialized': False, 'error': None, 'required': False}
}

# CRITICAL: Module initialization order - web module MUST be first to handle the root route
MODULE_INIT_ORDER = ['web', 'malware', 'detonation', 'viz']

def get_module(module_name):
    """Get module by name, for inter-module communication.
    
    Args:
        module_name (str): Name of the module to retrieve
        
    Returns:
        module or None: The imported module or None if not found
    """
    if module_name not in MODULES:
        logger.warning(f"Requested unknown module: {module_name}")
        return None
        
    try:
        # Get module path from registry
        module_path = MODULES[module_name]['path']
        
        # Check if module is already imported
        if module_path in sys.modules:
            return sys.modules[module_path]
            
        # Import the module and update status
        module = importlib.import_module(module_path)
        MODULES[module_name]['initialized'] = True
        MODULES[module_name]['error'] = None
        return module
    except ImportError as e:
        error_msg = f"Error importing module {module_name}: {e}"
        logger.error(error_msg)
        MODULES[module_name]['error'] = error_msg
        return None
    except Exception as e:
        error_msg = f"Unexpected error with module {module_name}: {e}"
        logger.error(error_msg)
        MODULES[module_name]['error'] = error_msg
        return None

def handle_not_found(e):
    """Handle 404 errors gracefully with custom page"""
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

def handle_server_error(e):
    """Handle 500 errors with helpful context"""
    error_traceback = traceback.format_exc()
    logger.error(f"Server error: {str(e)}\n{error_traceback}")
    
    try:
        return render_template('error.html', 
                              error_code=500,
                              error_message=f"Server error: {str(e)}",
                              error_details=error_traceback), 500
    except Exception:
        # Fallback to basic HTML if template rendering fails
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Server Error</title>
            <style>
                body {{ font-family: Arial, sans-serif; text-align: center; margin-top: 50px; }}
                h1 {{ color: #dc3545; }}
                .error-details {{ text-align: left; background: #f8f9fa; padding: 15px; margin: 20px; overflow: auto; }}
                a {{ color: #4a6fa5; text-decoration: none; }}
                a:hover {{ text-decoration: underline; }}
            </style>
        </head>
        <body>
            <h1>500 - Server Error</h1>
            <p>The server encountered an internal error.</p>
            <div class="error-details">
                <p><strong>Error:</strong> {str(e)}</p>
                <pre>{error_traceback}</pre>
            </div>
            <p><a href="/">Return to Home</a></p>
        </body>
        </html>
        """, 500

def ensure_directories():
    """Ensure all required directories exist for application.
    
    Creates directories for templates, static files, uploads, database, and logs.
    """
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
            logger.debug(f"Ensured directory exists: {directory}")
        except Exception as e:
            logger.error(f"Error creating directory {directory}: {e}")

def ensure_base_templates():
    """Ensure base templates exist by leveraging web_interface module.
    
    Falls back to creating minimal templates directly if the module fails.
    """
    try:
        # Try to use the web module's function
        web_module = get_module('web')
        if web_module and hasattr(web_module, 'generate_base_templates'):
            web_module.generate_base_templates()
            logger.info("Base templates have been created or verified by web module")
            return
    except Exception as e:
        logger.error(f"Error using web module for template generation: {e}")
    
    # Fallback - create minimal templates directly
    try:
        templates_dir = os.path.join(os.getcwd(), 'templates')
        os.makedirs(templates_dir, exist_ok=True)
        
        # Create minimal base.html
        base_path = os.path.join(templates_dir, 'base.html')
        if not os.path.exists(base_path) or os.path.getsize(base_path) < 100:
            with open(base_path, 'w') as f:
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
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="alert alert-{{ category }}">{{ message }}</div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        {% block content %}{% endblock %}
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>""")
        
        # Create minimal index.html
        index_path = os.path.join(templates_dir, 'index.html')
        if not os.path.exists(index_path) or os.path.getsize(index_path) < 100:
            with open(index_path, 'w') as f:
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
        error_path = os.path.join(templates_dir, 'error.html')
        if not os.path.exists(error_path) or os.path.getsize(error_path) < 100:
            with open(error_path, 'w') as f:
                f.write("""{% extends 'base.html' %}
{% block content %}
<div class="alert alert-danger">
    <h1>Error {{ error_code }}</h1>
    <p>{{ error_message }}</p>
    {% if error_details %}
    <pre class="mt-3">{{ error_details }}</pre>
    {% endif %}
</div>
<a href="/" class="btn btn-primary">Return to Home</a>
{% endblock %}""")
        
        logger.info("Created minimal fallback templates")
    except Exception as e:
        logger.error(f"Failed to create fallback templates: {e}")

def initialize_database(app):
    """Initialize the database with robust error handling."""
    try:
        with app.app_context():
            try:
                # First try to import and use the unified database module
                from database import init_app as init_db
                init_db(app)
                logger.info("Database initialized using database module")
            except ImportError:
                logger.warning("Database module not found, trying fallback initialization")
                # Look for database init in web module
                web_module = get_module('web')
                if web_module and hasattr(web_module, 'ensure_db_tables'):
                    web_module.ensure_db_tables(app)
                    logger.info("Database initialized using web module")
                else:
                    logger.warning("No database initialization functions found")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        logger.warning("Application will start but database functionality may be limited")

def initialize_modules(app):
    """Initialize all modules in the correct order with robust error handling."""
    with app.app_context():
        for module_name in MODULE_INIT_ORDER:
            if module_name not in MODULES:
                logger.warning(f"Module {module_name} in init order but not in registry")
                continue
                
            module_info = MODULES[module_name]
            required = module_info.get('required', False)
            
            try:
                logger.info(f"Initializing module: {module_name}")
                module = get_module(module_name)
                
                if module and hasattr(module, 'init_app'):
                    module.init_app(app)
                    module_info['initialized'] = True
                    module_info['error'] = None
                    logger.info(f"Successfully initialized module: {module_name}")
                else:
                    if not module:
                        error_msg = f"Module {module_name} could not be imported"
                    else:
                        error_msg = f"Module {module_name} has no init_app function"
                        
                    logger.warning(error_msg)
                    module_info['error'] = error_msg
                    
                    if required:
                        raise ImportError(f"Required module {module_name} failed to initialize: {error_msg}")
            except Exception as e:
                error_msg = f"Error initializing module {module_name}: {str(e)}"
                logger.error(error_msg)
                logger.debug(traceback.format_exc())
                
                module_info['initialized'] = False
                module_info['error'] = error_msg
                
                if required:
                    raise ImportError(f"Required module {module_name} failed to initialize: {error_msg}")

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
        
        # Load configuration, with defaults for critical settings
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
        app.register_error_handler(500, handle_server_error)
        logger.info("Registered error handlers")
        
        # Initialize LoginManager
        login_manager = LoginManager()
        login_manager.init_app(app)
        login_manager.login_view = 'web.login'
        login_manager.login_message = "Please log in to access this page."
        logger.info("Login manager initialized")
        
        # User loader function for Flask-Login
        @login_manager.user_loader
        def load_user(user_id):
            """Load user by ID for Flask-Login with fault tolerance"""
            try:
                # Import from web_interface for consistency
                web_module = get_module('web')
                if web_module and hasattr(web_module, 'load_user'):
                    return web_module.load_user(user_id)
                    
                # Fallback if the function isn't available in web_interface
                try:
                    from database import get_db_connection
                    with get_db_connection(row_factory=lambda cursor, row: dict(row)) as conn:
                        cursor = conn.cursor()
                        cursor.execute("SELECT id, username, role FROM users WHERE id = ?", (user_id,))
                        user_data = cursor.fetchone()
                        if user_data:
                            from web_interface import User
                            return User(user_data['id'], user_data['username'], user_data['role'])
                except ImportError:
                    logger.warning("Could not import database module for user loading")
                    
                # Ultimate fallback - try direct SQLite access
                try:
                    import sqlite3
                    conn = sqlite3.connect(app.config['DATABASE_PATH'])
                    conn.row_factory = sqlite3.Row
                    cursor = conn.cursor()
                    cursor.execute("SELECT id, username, role FROM users WHERE id = ?", (user_id,))
                    user_data = cursor.fetchone()
                    conn.close()
                    
                    if user_data:
                        # Create User class inline if needed
                        class User:
                            def __init__(self, id, username, role):
                                self.id = id
                                self.username = username
                                self.role = role
                                
                            def is_authenticated(self):
                                return True
                                
                            def is_active(self):
                                return True
                                
                            def is_anonymous(self):
                                return False
                                
                            def get_id(self):
                                return str(self.id)
                                
                        return User(user_data['id'], user_data['username'], user_data['role'])
                except Exception as e:
                    logger.error(f"Ultimate fallback for user loading failed: {e}")
            except Exception as e:
                logger.error(f"Error loading user: {e}")
            return None
        
        # Ensure basic templates exist before anything else
        ensure_base_templates()
        
        # Initialize database early to ensure it exists
        if not app.config.get('SKIP_DB_INIT', False):
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
            # Build comprehensive health data
            health_data = {
                "status": "healthy",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "uptime_seconds": int(time.time() - app.config.get('START_TIME', 0)),
                "components": {
                    "modules": {name: {
                        "initialized": info.get("initialized", False),
                        "error": info.get("error", None)
                    } for name, info in MODULES.items()}
                }
            }
            
            # Check database health
            try:
                import sqlite3
                conn = sqlite3.connect(app.config.get('DATABASE_PATH'))
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
                conn.close()
                health_data["components"]["database"] = {"status": "healthy"}
            except Exception as e:
                health_data["components"]["database"] = {"status": "unhealthy", "error": str(e)}
                health_data["status"] = "degraded"
            
            # Determine overall health status
            for module_info in health_data["components"]["modules"].values():
                if module_info.get("error") is not None:
                    health_data["status"] = "degraded"
                    break
            
            return jsonify(health_data)
        
        # Initialize modules in the defined order
        try:
            initialize_modules(app)
        except Exception as e:
            logger.error(f"Critical error during module initialization: {e}")
            logger.error(traceback.format_exc())
            # Continue with limited functionality
        
        # Add alternate routes for the root path to handle edge cases
        @app.route('/index')
        @app.route('/home')
        @app.route('/start')
        def redirect_to_root():
            logger.debug("Redirecting alternate root URLs to /")
            return redirect(url_for('web.index'))
        
        # Diagnostic route for debugging
        @app.route('/debug-info')
        def debug_info():
            """Endpoint for debugging template and module issues"""
            debug_data = {
                'app_config': {k: str(v) for k, v in app.config.items() if k != 'SECRET_KEY'},
                'template_dir': app.template_folder,
                'static_dir': app.static_folder,
                'template_dir_exists': os.path.exists(app.template_folder),
                'static_dir_exists': os.path.exists(app.static_folder),
                'template_files': os.listdir(app.template_folder) if os.path.exists(app.template_folder) else [],
                'static_files': os.listdir(app.static_folder) if os.path.exists(app.static_folder) else [],
                'module_status': {name: {
                    "initialized": info.get("initialized", False),
                    "error": info.get("error", None)
                } for name, info in MODULES.items()},
                'database_path': app.config.get('DATABASE_PATH'),
                'database_exists': os.path.exists(app.config.get('DATABASE_PATH'))
            }
            
            return jsonify(debug_data)
        
        # Mark application as ready
        try:
            # Try to use app_ready module if available
            try:
                from app_ready import mark_app_ready
                mark_app_ready()
                logger.info("Application marked as ready using app_ready module")
            except ImportError:
                # Create our own marker file
                ready_path = os.path.join(app.config.get('UPLOAD_FOLDER', '/app/data'), '.app_ready')
                with open(ready_path, 'w') as f:
                    f.write('ready')
                logger.info(f"Application marked as ready with marker file at {ready_path}")
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
