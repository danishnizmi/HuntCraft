from flask import Flask, current_app
import os
import sqlite3
import logging
import importlib
from pathlib import Path

# Module configuration
MODULES = {
    'malware': 'malware_module',
    'detonation': 'detonation_module',
    'viz': 'viz_module',
    'web': 'web_interface'
}

def create_app(test_config=None):
    """Application factory to create and configure the Flask app"""
    # Create and configure the app
    app = Flask(__name__, 
                static_folder='static',
                template_folder='templates')
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
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
            ENABLE_VISUALIZATION=True,
            GENERATE_TEMPLATES=os.environ.get('GENERATE_TEMPLATES', 'False').lower() in ('true', '1', 't')
        )
    
    # Setup essential directories
    for directory in [app.config.get('UPLOAD_FOLDER', '/app/data/uploads'), 'static/css', 
                     'static/js', 'templates', 
                     os.path.dirname(app.config.get('DATABASE_PATH', '/app/data/malware_platform.db'))]:
        os.makedirs(directory, exist_ok=True)
    
    # Initialize database
    from database import init_app as init_db
    init_db(app)
    
    # Load all modules eagerly at startup
    logger.info("Loading all modules at startup")
    for module_name, module_path in MODULES.items():
        try:
            module = importlib.import_module(module_path)
            if hasattr(module, 'init_app'):
                module.init_app(app)
                logger.info(f"Initialized module: {module_name}")
        except ImportError as e:
            logger.error(f"Failed to import module {module_name}: {str(e)}")
    
    # Ensure we have a minimal index.html template
    with app.app_context():
        ensure_index_template(app)
    
    # Health check endpoint
    @app.route('/health')
    def health_check():
        return {'status': 'healthy'}, 200
    
    # Simple error handlers
    @app.errorhandler(404)
    def page_not_found(e):
        return f"Page not found: {str(e)}", 404

    @app.errorhandler(500)
    def server_error(e):
        return f"Server error: {str(e)}", 500
    
    return app

def ensure_index_template(app):
    """Create a minimal index.html if it doesn't exist"""
    if not os.path.exists('templates/index.html'):
        os.makedirs('templates', exist_ok=True)
        with open('templates/index.html', 'w') as f:
            f.write("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ app_name }}</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; text-align: center; }
        h1 { color: #4a6fa5; }
        .card { background: #f8f9fa; border-radius: 8px; padding: 20px; margin-top: 20px; }
    </style>
</head>
<body>
    <h1>{{ app_name }}</h1>
    <div class="card">
        <p>The application is running. Use the links below to navigate:</p>
        <ul style="list-style:none; padding:0;">
            <li><a href="/malware">Malware Analysis</a></li>
            <li><a href="/detonation">Detonation Service</a></li>
            <li><a href="/viz">Visualizations</a></li>
        </ul>
    </div>
</body>
</html>""")
        logging.getLogger(__name__).info("Created minimal index.html template")

if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
