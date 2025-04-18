from flask import Flask, render_template, jsonify, g, request, redirect, url_for
import os
import logging
import importlib
import time
import sys
import traceback

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Core module configuration
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
    """Get module by name, for inter-module communication."""
    if module_name not in MODULES:
        return None
        
    try:
        # Check if module is already imported
        if module_name in sys.modules:
            return sys.modules[MODULES[module_name]]
            
        # Import the module
        module = importlib.import_module(MODULES[module_name])
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

def ensure_index_template(app):
    """Create a minimal index.html if it doesn't exist or is too small."""
    template_dir = app.template_folder
    if not os.path.isabs(template_dir):
        template_dir = os.path.join(app.root_path, template_dir)
            
    # Ensure directory exists
    logger.info(f"Ensuring templates exist in directory: {template_dir}")
    os.makedirs(template_dir, exist_ok=True)
    
    # Create base.html if it doesn't exist or is too small
    base_path = os.path.join(template_dir, 'base.html')
    
    # Check if base.html exists and has adequate content
    needs_create = False
    if not os.path.exists(base_path):
        needs_create = True
        logger.info("base.html does not exist, will create it")
    else:
        # Check file size
        try:
            with open(base_path, 'r') as f:
                content = f.read()
                if len(content) < 100:  # Too small to be a proper template
                    needs_create = True
                    logger.warning(f"base.html exists but is too small ({len(content)} bytes), will recreate it")
                else:
                    logger.info(f"Successfully verified base.html is readable ({len(content)} bytes)")
        except Exception as e:
            needs_create = True
            logger.error(f"Error reading base.html: {e}, will recreate it")
    
    if needs_create:
        try:
            with open(base_path, 'w') as f:
                f.write("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}{{ app_name }}{% endblock %}</title>
    
    <!-- Bootstrap CSS -->
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    
    <!-- Font Awesome for icons -->
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    
    <!-- Custom CSS -->
    <link href="{{ url_for('static', filename='css/main.css') }}" rel="stylesheet">
    {% block head %}{% endblock %}
    
    <style>
        .navbar { background-color: {{ colors.primary|default('#4a6fa5') }} !important; }
        .btn-primary { background-color: {{ colors.primary|default('#4a6fa5') }}; border-color: {{ colors.primary|default('#4a6fa5') }}; }
        .btn-primary:hover { background-color: {{ colors.primary|default('#4a6fa5') }}; filter: brightness(90%); }
    </style>
</head>
<body>
    <!-- Navigation -->
    <nav class="navbar navbar-expand-lg navbar-dark">
        <div class="container">
            <a class="navbar-brand" href="/">{{ app_name }}</a>
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
                <span class="navbar-toggler-icon"></span>
            </button>
            <div class="collapse navbar-collapse" id="navbarNav">
                <ul class="navbar-nav me-auto">
                    <li class="nav-item"><a class="nav-link" href="/">Home</a></li>
                    {% if current_user.is_authenticated %}
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('web.dashboard') }}">Dashboard</a></li>
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('malware.index') }}">Malware</a></li>
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('detonation.index') }}">Detonation</a></li>
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('viz.index') }}">Visualizations</a></li>
                    {% endif %}
                </ul>
                <ul class="navbar-nav">
                    {% if current_user.is_authenticated %}
                    <li class="nav-item dropdown">
                        <a class="nav-link dropdown-toggle" href="#" id="userDropdown" role="button" data-bs-toggle="dropdown">
                            <i class="fas fa-user"></i> {{ current_user.username }}
                        </a>
                        <ul class="dropdown-menu dropdown-menu-end">
                            <li><a class="dropdown-item" href="{{ url_for('web.profile') }}">Profile</a></li>
                            {% if current_user.role == 'admin' %}
                            <li><a class="dropdown-item" href="{{ url_for('web.users') }}">User Management</a></li>
                            <li><a class="dropdown-item" href="{{ url_for('web.infrastructure') }}">Infrastructure</a></li>
                            {% endif %}
                            <li><hr class="dropdown-divider"></li>
                            <li><a class="dropdown-item" href="{{ url_for('web.logout') }}">Logout</a></li>
                        </ul>
                    </li>
                    {% else %}
                    <li class="nav-item"><a class="nav-link" href="{{ url_for('web.login') }}"><i class="fas fa-sign-in-alt"></i> Login</a></li>
                    {% endif %}
                </ul>
            </div>
        </div>
    </nav>

    <!-- Main Content -->
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

    <!-- Footer -->
    <footer class="mt-5 py-3 text-center text-muted">
        <div class="container">
            <p>&copy; {{ year|default('2025') }} {{ app_name }}</p>
        </div>
    </footer>

    <!-- Bootstrap JS Bundle with Popper -->
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    
    <!-- Custom JS -->
    <script src="{{ url_for('static', filename='js/main.js') }}"></script>
    {% block scripts %}{% endblock %}
</body>
</html>""")
            logger.info("Created base.html template")
        except Exception as e:
            logger.error(f"Error generating base.html: {e}")
    
    # Create index.html if it doesn't exist or is too small
    index_path = os.path.join(template_dir, 'index.html')
    
    # Check if index.html exists and has adequate content
    needs_create = False
    if not os.path.exists(index_path):
        needs_create = True
        logger.info("index.html does not exist, will create it")
    else:
        # Check file size
        try:
            with open(index_path, 'r') as f:
                content = f.read()
                if len(content) < 100:  # Too small to be a proper template
                    needs_create = True
                    logger.warning(f"index.html exists but is too small ({len(content)} bytes), will recreate it")
                else:
                    logger.info(f"Successfully verified index.html is readable ({len(content)} bytes)")
        except Exception as e:
            needs_create = True
            logger.error(f"Error reading index.html: {e}, will recreate it")
    
    if needs_create:
        try:
            with open(index_path, 'w') as f:
                f.write("""{% extends 'base.html' %}

{% block title %}{{ app_name }}{% endblock %}

{% block content %}
<div class="jumbotron bg-light p-5 rounded">
    <h1 class="display-4">Welcome to {{ app_name }}</h1>
    <p class="lead">A secure platform for malware analysis and detonation.</p>
    <hr class="my-4">
    <p>Use the navigation bar above to access different features of the platform.</p>
    {% if not current_user.is_authenticated %}
    <a class="btn btn-primary btn-lg" href="{{ url_for('web.login') }}" role="button">Login</a>
    {% else %}
    <a class="btn btn-primary btn-lg" href="{{ url_for('web.dashboard') }}" role="button">Go to Dashboard</a>
    {% endif %}
</div>

<div class="row mt-5">
    <div class="col-md-4">
        <div class="card">
            <div class="card-body text-center">
                <i class="fas fa-virus fa-3x mb-3 text-primary"></i>
                <h5 class="card-title">Malware Analysis</h5>
                <p class="card-text">Upload and analyze malware samples securely.</p>
                <a href="{{ url_for('malware.index') }}" class="btn btn-outline-primary">Analyze Malware</a>
            </div>
        </div>
    </div>
    
    <div class="col-md-4">
        <div class="card">
            <div class="card-body text-center">
                <i class="fas fa-flask fa-3x mb-3 text-primary"></i>
                <h5 class="card-title">Detonation Services</h5>
                <p class="card-text">Detonate samples in an isolated environment.</p>
                <a href="{{ url_for('detonation.index') }}" class="btn btn-outline-primary">Detonation Zone</a>
            </div>
        </div>
    </div>
    
    <div class="col-md-4">
        <div class="card">
            <div class="card-body text-center">
                <i class="fas fa-chart-line fa-3x mb-3 text-primary"></i>
                <h5 class="card-title">Visualizations</h5>
                <p class="card-text">Visualize data and create reports.</p>
                <a href="{{ url_for('viz.index') }}" class="btn btn-outline-primary">View Analytics</a>
            </div>
        </div>
    </div>
</div>

<div class="row mt-4">
    <div class="col-12">
        <div class="card">
            <div class="card-body text-center">
                <i class="fas fa-wrench fa-2x mb-3 text-primary"></i>
                <h5 class="card-title">Diagnostics</h5>
                <p class="card-text">Check system status and troubleshoot issues.</p>
                <a href="{{ url_for('web.diagnostic') }}" class="btn btn-outline-primary">System Diagnostics</a>
            </div>
        </div>
    </div>
</div>
{% endblock %}""")
                logger.info("Created index.html template")
        except Exception as e:
            logger.error(f"Error generating index.html: {e}")
    
    # Create error.html if it doesn't exist
    error_path = os.path.join(template_dir, 'error.html')
    if not os.path.exists(error_path):
        try:
            with open(error_path, 'w') as f:
                f.write("""{% extends 'base.html' %}

{% block title %}Error {{ error_code }} - {{ app_name }}{% endblock %}

{% block content %}
<div class="row justify-content-center mt-5">
    <div class="col-md-8">
        <div class="card text-center">
            <div class="card-header bg-danger text-white">
                <h2 class="card-title">Error {{ error_code }}</h2>
            </div>
            <div class="card-body">
                <p class="display-1 text-danger"><i class="fas fa-exclamation-triangle"></i></p>
                <h4>{{ error_message }}</h4>
                <p class="text-muted">Please try again or contact your system administrator if the problem persists.</p>
                
                {% if error_details and config.get('DEBUG', False) %}
                <div class="alert alert-secondary mt-4">
                    <h5>Debug Details</h5>
                    <pre class="text-start"><code>{{ error_details }}</code></pre>
                </div>
                {% endif %}
                
                <a href="/" class="btn btn-primary mt-3">Return to Home</a>
            </div>
        </div>
    </div>
</div>
{% endblock %}""")
                logger.info("Created error.html template")
        except Exception as e:
            logger.error(f"Error generating error.html: {e}")
    
    # Check what templates are in the directory
    try:
        template_files = os.listdir(template_dir)
        logger.info(f"Templates directory contains: {template_files}")
    except Exception as e:
        logger.error(f"Error listing templates directory: {e}")

# Template generation utility (to be used by all modules)
def generate_template(template_path, content, force=False):
    """Generate a template file if it doesn't exist or force=True.
    
    Args:
        template_path (str): Path where template should be saved
        content (str): Template content
        force (bool): If True, overwrite existing template
    
    Returns:
        bool: True if template was created or updated, False otherwise
    """
    try:
        if force or not os.path.exists(template_path):
            os.makedirs(os.path.dirname(template_path), exist_ok=True)
            with open(template_path, 'w') as f:
                f.write(content)
            logger.info(f"Generated template: {os.path.basename(template_path)}")
            return True
        return False
    except Exception as e:
        logger.error(f"Error generating template {template_path}: {e}")
        return False

def detect_installed_features():
    """Detect features available in the current environment"""
    features = {}
    
    # Check for visualization dependencies
    try:
        import pandas
        features['pandas'] = True
        
        try:
            import numpy
            features['numpy'] = True
        except ImportError:
            features['numpy'] = False
            
        try:
            import plotly
            features['plotly'] = True
        except ImportError:
            features['plotly'] = False
    except ImportError:
        features['pandas'] = False
        features['numpy'] = False
        features['plotly'] = False
        
    # Check for Google Cloud libraries
    try:
        import google.cloud.storage
        features['gcp_storage'] = True
    except ImportError:
        features['gcp_storage'] = False
        
    try:
        import google.cloud.compute_v1
        features['gcp_compute'] = True
    except ImportError:
        features['gcp_compute'] = False
        
    try:
        import google.cloud.pubsub_v1
        features['gcp_pubsub'] = True
    except ImportError:
        features['gcp_pubsub'] = False
    
    # Check for stub modules
    try:
        import ssdeep
        # Test if it's a real implementation
        try:
            test_hash = ssdeep.hash("test")
            features['real_ssdeep'] = test_hash != "stub_hash"
        except:
            features['real_ssdeep'] = False
    except ImportError:
        features['real_ssdeep'] = False
        
    # Check scripts availability
    scripts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts')
    features['scripts_dir_exists'] = os.path.isdir(scripts_dir)
    
    if features['scripts_dir_exists']:
        features['reporting_script'] = os.path.exists(os.path.join(scripts_dir, 'reporting.py'))
        features['sanitizer_script'] = os.path.exists(os.path.join(scripts_dir, 'sanitizer.py'))
        
    logger.info(f"Feature detection completed: {features}")
    return features

def integrate_script(script_name):
    """Safely import a script from the scripts directory
    
    Args:
        script_name (str): Name of the script without .py extension
        
    Returns:
        module or None: Imported module if successful, None otherwise
    """
    try:
        # Check if script exists
        script_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 
            'scripts', 
            f"{script_name}.py"
        )
        
        if not os.path.exists(script_path):
            logger.warning(f"Script {script_name}.py not found at {script_path}")
            return None
            
        # Import the script
        script_module = importlib.import_module(f"scripts.{script_name}")
        logger.info(f"Successfully integrated script: {script_name}")
        return script_module
    except ImportError as e:
        logger.warning(f"Could not import script {script_name}: {e}")
        return None
    except Exception as e:
        logger.error(f"Error integrating script {script_name}: {e}")
        return None

def get_sanitizer():
    """Get sanitizer module from scripts directory"""
    return integrate_script("sanitizer")
    
def get_reporting():
    """Get reporting module from scripts directory"""
    return integrate_script("reporting")

def register_health_check(app):
    """Register a comprehensive health check endpoint
    
    Args:
        app: Flask application instance
    """
    @app.route('/health')
    def health_check():
        """Comprehensive health check endpoint"""
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
                "modules": module_status,
                "features": detect_installed_features()
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
        
        # Load configuration
        app.config.update({
            'DATABASE_PATH': os.environ.get('DATABASE_PATH', '/app/data/malware_platform.db'),
            'UPLOAD_FOLDER': os.environ.get('UPLOAD_FOLDER', '/app/data/uploads'),
            'MAX_UPLOAD_SIZE_MB': int(os.environ.get('MAX_UPLOAD_SIZE_MB', 100)),
            'DEBUG': os.environ.get('DEBUG', 'False').lower() in ('true', '1', 't'),
            'APP_NAME': os.environ.get('APP_NAME', "Malware Detonation Platform"),
            'GENERATE_TEMPLATES': os.environ.get('GENERATE_TEMPLATES', 'True').lower() in ('true', '1', 't'),
            'INITIALIZE_GCP': os.environ.get('INITIALIZE_GCP', 'False').lower() in ('true', '1', 't'),
            'SKIP_DB_INIT': os.environ.get('SKIP_DB_INIT', 'False').lower() in ('true', '1', 't'),
            'START_TIME': start_time
        })
        
        # Set MAX_CONTENT_LENGTH based on MAX_UPLOAD_SIZE_MB
        app.config['MAX_CONTENT_LENGTH'] = app.config['MAX_UPLOAD_SIZE_MB'] * 1024 * 1024
        
        # Check web interface configuration
        logger.info("Checking web interface configuration")
        try:
            # Just import and check if web_bp is defined correctly
            from web_interface import web_bp
            logger.info(f"Web blueprint configuration: url_prefix={web_bp.url_prefix}")
        except Exception as e:
            logger.warning(f"Could not check web blueprint configuration: {e}")
        
        # *** CRITICAL: REGISTER ROOT ROUTE FIRST AND DIRECTLY ON APP ***
        @app.route('/')
        def root():
            """Primary root route handler."""
            logger.info("Primary root handler called")
            try:
                return render_template('index.html')
            except Exception as e:
                logger.error(f"Error in primary root handler: {e}")
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
        
        logger.info("Direct root route registered as primary handler")
        
        # Register error handlers
        app.register_error_handler(404, handle_not_found)
        logger.info("Registered 404 error handler")
        
        # Create required directories with better error handling
        setup_dirs = [
            os.path.dirname(app.config.get('DATABASE_PATH')),
            app.config.get('UPLOAD_FOLDER'),
            os.path.join(app.static_folder, 'css'),
            os.path.join(app.static_folder, 'js'),
            app.template_folder
        ]
        
        for directory in setup_dirs:
            try:
                os.makedirs(directory, exist_ok=True)
                logger.debug(f"Ensured directory exists: {directory}")
            except Exception as e:
                logger.error(f"Error creating directory {directory}: {e}")
        
        # Register consolidated health check endpoint
        register_health_check(app)
        
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
        
        # Ensure essential templates exist
        if app.config.get('GENERATE_TEMPLATES', False):
            ensure_index_template(app)
        
        # Initialize database with better error handling
        try:
            with app.app_context():
                # Make sure database directory exists
                db_dir = os.path.dirname(app.config.get('DATABASE_PATH'))
                os.makedirs(db_dir, exist_ok=True)
                
                # Initialize database
                from database import init_app as init_db
                init_db(app)
                logger.info("Database initialized successfully")
        except Exception as e:
            logger.error(f"Database initialization error: {e}")
            logger.warning("Application will start but database functionality may be limited")
        
        # CRITICAL CHANGE: Initialize modules in a different order, with web blueprint first
        with app.app_context():
            # First register web blueprint directly for root route handling
            try:
                from web_interface import web_bp
                # CRITICAL: Register with empty URL prefix and ensure it takes precedence
                web_bp.url_prefix = None  # Explicitly set to None, not empty string
                app.register_blueprint(web_bp, url_prefix=None)  # Use None to avoid any Flask string concatenation issues
                logger.info("Direct web blueprint registration successful")
                module_status['web']['initialized'] = True
            except Exception as e:
                logger.error(f"Error directly registering web blueprint: {e}")
                logger.warning("Web interface may not function properly - root route and UI features might be unavailable")
                module_status['web']['error'] = str(e)
            
            # Now initialize other modules in the defined order
            for module_name in MODULE_INIT_ORDER:
                # Skip web as we already initialized it
                if module_name == 'web':
                    continue
                    
                try:
                    module = get_module(module_name)
                    if module and hasattr(module, 'init_app'):
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
            return redirect(url_for('root'))
        
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
        
        logger.info("Emergency application created as fallback")
        return emergency_app

if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=app.config.get('DEBUG', False))
