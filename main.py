from flask import Flask
import os
import sqlite3
from pathlib import Path

# Import the core modules
import data_module
import analysis_module
import visualization_module
import web_interface_module
import config

def create_app(test_config=None):
    """Application factory to create and configure the Flask app"""
    # Create and configure the app
    app = Flask(__name__, 
                static_folder='static',
                template_folder='templates')
    
    # Load configuration
    if test_config:
        app.config.update(test_config)
    else:
        app.config.from_object(config.Config)
    
    # Ensure required directories exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs('static/css', exist_ok=True)
    os.makedirs('static/js', exist_ok=True)
    os.makedirs('templates', exist_ok=True)
    
    # Initialize database
    _init_database(app.config['DATABASE_PATH'])
    
    # Register all module blueprints
    data_module.init_app(app)
    analysis_module.init_app(app)
    visualization_module.init_app(app)
    web_interface_module.init_app(app)
    
    # Register error handlers
    @app.errorhandler(404)
    def page_not_found(e):
        return web_interface_module.handle_404(), 404

    @app.errorhandler(500)
    def server_error(e):
        return web_interface_module.handle_500(), 500
    
    return app

def _init_database(db_path):
    """Initialize the database with core tables"""
    # Ensure directory exists
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    # Connect to the database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create the tables using schema from modules
    data_module.create_database_schema(cursor)
    analysis_module.create_database_schema(cursor)
    visualization_module.create_database_schema(cursor)
    
    # Commit changes and close connection
    conn.commit()
    conn.close()

if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=app.config['DEBUG'])
