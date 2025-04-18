# main.py - Modified with centralized utility functions
from flask import Flask, render_template, jsonify, g, request
import os
import logging
import importlib
import time
import sys
import traceback
from database import close_db

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

def direct_root_handler():
    """Direct root handler for fallback."""
    try:
        return render_template('index.html')
    except Exception as e:
        logger.error(f"Error in direct root handler: {e}")
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Malware Detonation Platform</title>
            <style>
                body { font-family: Arial, sans-serif; text-align: center; margin-top: 50px; }
                h1 { color: #4a6fa5; }
                .links a { display: inline-block; margin: 10px; padding: 8px 16px; color: white; 
                          background-color: #4a6fa5; text-decoration: none; border-radius: 4px; }
            </style>
        </head>
        <body>
            <h1>Malware Detonation Platform</h1>
            <p>Welcome to the Malware Detonation Platform</p>
            <div class="links">
                <a href="/malware">Malware Analysis</a>
                <a href="/detonation">Detonation Service</a>
                <a href="/viz">Visualizations</a>
                <a href="/diagnostic">System Diagnostics</a>
            </div>
        </body>
        </html>
        """

def ensure_index_template(app):
    """Create a minimal index.html if it doesn't exist."""
    template_dir = app.template_folder
    if not os.path.isabs(template_dir):
        template_dir = os.path.join(app.root_path, template_dir)
            
    # Ensure directory exists
    os.makedirs(template_dir, exist_ok=True)
    
    # Create base.html if it doesn't exist
    base_path = os.path.join(template_dir, 'base.html')
    if not os.path.exists(base_path):
        with open(base_path, 'w') as f:
            f.write("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}{{ app_name }}{% endblock %}</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
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
    
    # Create index.html if it doesn't exist
    index_path = os.path.join(template_dir, 'index.html')
    if not os.path.exists(index_path):
        with open(index_path, 'w') as f:
            f.write("""{% extends 'base.html' %}

{% block title %}{{ app_name }}{% endblock %}

{% block content %}
<div class="card">
    <h2>Welcome to {{ app_name }}</h2>
    <p>A secure platform for malware analysis and detonation.</p>
    <div>
        <a href="/malware">Malware Analysis</a> |
        <a href="/detonation">Detonation Service</a> |
        <a href="/viz">Visualizations</a> |
        <a href="/diagnostic">Diagnostics</a>
    </div>
</div>
{% endblock %}""")
            
    # Create error.html if it doesn't exist
    error_path = os.path.join(template_dir, 'error.html')
    if not os.path.exists(error_path):
        with open(error_path, 'w') as f:
            f.write("""{% extends 'base.html' %}
{% block title %}Error{% endblock %}
{% block content %}
<div class="card">
    <h2>Error {{ error_code }}</h2>
    <p>{{ error_message }}</p>
    {% if error_details %}
    <pre>{{ error_details }}</pre>
    {% endif %}
    <a href="/">Return Home</a>
</div>
{% endblock %}""")

def feature_detection():
    """Detect available features and stub implementations"""
    features = {}
    
    # Check for visualization libraries
    try:
        import pandas
        import numpy
        features['pandas_numpy'] = True
        
        try:
            import plotly
            features['plotly'] = True
        except ImportError:
            features['plotly'] = False
    except ImportError:
        features['pandas_numpy'] = False
        features['plotly'] = False
    
    # Check for GCP libraries
    try:
        import google.cloud.storage
        import google.cloud.compute_v1
        features['gcp'] = True
    except ImportError:
        features['gcp'] = False
    
    # Check for stub modules vs real ones
    try:
        import ssdeep
        # Test if it's a stub by checking for stub_hash
        test_hash = ssdeep.hash("test")
        features['real_ssdeep'] = test_hash != "stub_hash"
    except (ImportError, AttributeError):
        features['real_ssdeep'] = False
    
    try:
        import yara
        # Try to compile a rule - stubs will fail
        try:
            rules = yara.compile(source="rule test { condition: true }")
            features['real_yara'] = True
        except:
            features['real_yara'] = False
    except ImportError:
        features['real_yara'] = False
        
    # Check for script integration readiness
    features['scripts_available'] = os.path.exists('scripts/reporting.py') and os.path.exists('scripts/sanitizer.py')
    
    return features

def register_unified_health_check(app):
    """Register a consolidated health check endpoint"""
    @app.route('/health')
    def health_check():
        from database import check_database_health
        
        health_data = {
            "status": "healthy",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "uptime_seconds": int(time.time() - app.config['START_TIME']),
            "database": check_database_health(),
            "modules": module_status,
            "features": feature_detection()
        }
        
        # Determine overall status
        if health_data["database"]["status"] != "healthy":
            health_data["status"] = "degraded"
            
        for module, status in module_status.items():
            if not status.get("initialized", False):
                health_data["status"] = "degraded"
                break
                
        return jsonify(health_data)

def create_app(test_config=None):
    """Create and configure the Flask application."""
    # Record start time for uptime tracking
    start_time = time.time()
    
    # Create Flask app with explicit template and static folders
    app = Flask(__name__, 
                static_folder='static',
                template_folder='templates')
    
    # Explicitly set the paths to avoid any path resolution issues
    app.static_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    app.template_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
    
    # Load configuration
    app.config.update({
        'DATABASE_PATH': os.environ.get('DATABASE_PATH', '/app/data/malware_platform.db'),
        'UPLOAD_FOLDER': os.environ.get('UPLOAD_FOLDER', '/app/data/uploads'),
        'MAX_UPLOAD_SIZE_MB': int(os.environ.get('MAX_UPLOAD_SIZE_MB', 100)),
        'DEBUG': os.environ.get('DEBUG', 'False').lower() in ('true', '1', 't'),
        'APP_NAME': os.environ.get('APP_NAME', "Malware Detonation Platform"),
        'GENERATE_TEMPLATES': os.environ.get('GENERATE_TEMPLATES', 'True').lower() in ('true', '1', 't'),
        'START_TIME': start_time
    })
    
    # Set MAX_CONTENT_LENGTH based on MAX_UPLOAD_SIZE_MB
    app.config['MAX_CONTENT_LENGTH'] = app.config['MAX_UPLOAD_SIZE_MB'] * 1024 * 1024
    
    # Create required directories
    setup_dirs = [
        os.path.dirname(app.config.get('DATABASE_PATH')),
        app.config.get('UPLOAD_FOLDER'),
        os.path.join(app.static_folder, 'css'),
        os.path.join(app.static_folder, 'js'),
        app.template_folder
    ]
    
    for directory in setup_dirs:
        os.makedirs(directory, exist_ok=True)
    
    # Register direct root handler as fallback
    app.add_url_rule('/', 'direct_root', direct_root_handler)
    
    # Register unified health check
    register_unified_health_check(app)
    
    # Set up request tracking
    @app.before_request
    def before_request():
        g.start_time = time.time()
        
    @app.after_request
    def after_request(response):
        if hasattr(g, 'start_time'):
            duration = time.time() - g.start_time
            response.headers['X-Request-Duration'] = str(duration)
        return response
    
    # Ensure templates exist
    ensure_index_template(app)
    
    # Initialize database
    try:
        with app.app_context():
            from database import init_app as init_db
            init_db(app)
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
    
    # Initialize modules
    with app.app_context():
        # First register web blueprint directly for root route handling
        try:
            from web_interface import web_bp
            app.register_blueprint(web_bp)
            logger.info("Direct web blueprint registration successful")
        except Exception as e:
            logger.error(f"Error directly registering web blueprint: {e}")
        
        # Now initialize modules in the defined order
        for module_name in MODULE_INIT_ORDER:
            try:
                module = get_module(module_name)
                if module and hasattr(module, 'init_app'):
                    module.init_app(app)
                    module_status[module_name]['initialized'] = True
                    logger.info(f"Module {module_name} initialized successfully")
            except Exception as e:
                logger.error(f"Error initializing module {module_name}: {e}")
                module_status[module_name]['error'] = str(e)
    
    # Mark application as ready
    try:
        from app_ready import mark_app_ready
        mark_app_ready()
        logger.info("Application marked as ready")
    except Exception as e:
        logger.warning(f"Could not mark application as ready: {e}")
    
    logger.info(f"Application startup completed in {time.time() - start_time:.2f} seconds")
    return app

# Template generation utility that can be used by multiple modules
def generate_template(template_path, content, force=False):
    """Generate a template file if it doesn't exist"""
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

if __name__ == "__main__":
    app = create_app()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=app.config.get('DEBUG', False))
