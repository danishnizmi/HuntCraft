"""Diagnostic module to help identify application startup issues."""

import os
import sys
import sqlite3
import logging
import importlib
import traceback
import threading
import time
from datetime import datetime

# Create a blueprint that can be registered early
from flask import Blueprint, render_template_string, jsonify, current_app

diagnostic_bp = Blueprint('diagnostic', __name__, url_prefix='/diagnostic')

# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Initialization status tracking
init_status = {
    'initialized': False,
    'start_time': time.time(),
    'modules': {},
    'errors': [],
    'database': {
        'status': 'unknown',
        'message': None,
        'tables': []
    },
    'environment': {},
    'python': {
        'version': sys.version,
        'path': sys.path,
        'modules': []
    }
}

def capture_environment():
    """Capture environment variables and configuration."""
    # Capture environment variables (excluding sensitive data)
    for key, value in os.environ.items():
        if not any(s in key.lower() for s in ['password', 'secret', 'key', 'token']):
            init_status['environment'][key] = value

def capture_module_info():
    """Capture information about loaded modules."""
    from main import MODULES
    
    for name, module_path in MODULES.items():
        try:
            module = sys.modules.get(module_path)
            
            if module:
                init_status['modules'][name] = {
                    'loaded': True,
                    'initialized': getattr(module, 'initialized', False),
                    'path': module_path,
                    'file': getattr(module, '__file__', 'unknown'),
                    'error': None
                }
            else:
                # Try to import the module
                try:
                    module = importlib.import_module(module_path)
                    init_status['modules'][name] = {
                        'loaded': True,
                        'initialized': getattr(module, 'initialized', False),
                        'path': module_path,
                        'file': getattr(module, '__file__', 'unknown'),
                        'error': None
                    }
                except Exception as e:
                    init_status['modules'][name] = {
                        'loaded': False,
                        'initialized': False,
                        'path': module_path,
                        'error': str(e)
                    }
        except Exception as e:
            init_status['modules'][name] = {
                'loaded': False,
                'initialized': False,
                'path': module_path,
                'error': str(e)
            }

def capture_installed_packages():
    """Capture information about installed Python packages."""
    try:
        import pkg_resources
        for package in pkg_resources.working_set:
            init_status['python']['modules'].append({
                'name': package.project_name,
                'version': package.version
            })
    except Exception as e:
        init_status['errors'].append(f"Error capturing package info: {str(e)}")

def check_database():
    """Check database connectivity and status."""
    try:
        db_path = current_app.config.get('DATABASE_PATH', '/app/data/malware_platform.db')
        init_status['database']['path'] = db_path
        
        if not os.path.exists(db_path):
            init_status['database']['status'] = 'missing'
            init_status['database']['message'] = f"Database file does not exist: {db_path}"
            return
        
        # Check if we can connect
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        
        if result and result[0] == 1:
            init_status['database']['status'] = 'connected'
            
            # Check tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            init_status['database']['tables'] = [table[0] for table in tables]
        else:
            init_status['database']['status'] = 'error'
            init_status['database']['message'] = "Database query failed"
        
        conn.close()
    except Exception as e:
        init_status['database']['status'] = 'error'
        init_status['database']['message'] = str(e)
        init_status['errors'].append(f"Database error: {str(e)}")

def check_file_permissions():
    """Check if files have correct permissions."""
    critical_paths = [
        '/app/data',
        '/app/data/uploads',
        '/app/static',
        '/app/templates'
    ]
    
    results = {}
    
    for path in critical_paths:
        try:
            if os.path.exists(path):
                stat_info = os.stat(path)
                test_file = os.path.join(path, '.test_write')
                can_write = False
                
                try:
                    with open(test_file, 'w') as f:
                        f.write('test')
                    os.remove(test_file)
                    can_write = True
                except Exception as e:
                    can_write = False
                
                results[path] = {
                    'exists': True,
                    'mode': stat_info.st_mode,
                    'writable': can_write
                }
            else:
                results[path] = {
                    'exists': False
                }
                # Try to create the directory
                try:
                    os.makedirs(path, exist_ok=True)
                    results[path]['created'] = True
                except Exception as e:
                    results[path]['created'] = False
                    results[path]['error'] = str(e)
        except Exception as e:
            results[path] = {
                'exists': 'error',
                'error': str(e)
            }
    
    init_status['file_permissions'] = results

@diagnostic_bp.route('/')
def index():
    """Main diagnostic page."""
    # Capture current state
    try:
        capture_environment()
    except Exception as e:
        init_status['errors'].append(f"Error capturing environment: {str(e)}")
    
    try:
        capture_module_info()
    except Exception as e:
        init_status['errors'].append(f"Error capturing module info: {str(e)}")
    
    try:
        capture_installed_packages()
    except Exception as e:
        init_status['errors'].append(f"Error capturing package info: {str(e)}")
    
    try:
        check_database()
    except Exception as e:
        init_status['errors'].append(f"Error checking database: {str(e)}")
    
    try:
        check_file_permissions()
    except Exception as e:
        init_status['errors'].append(f"Error checking file permissions: {str(e)}")
    
    # Update initialization status
    init_status['initialized'] = True
    init_status['uptime'] = time.time() - init_status['start_time']
    
    # Render the diagnostic information
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Application Diagnostics</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            h1 { color: #4a6fa5; }
            h2 { color: #6c757d; margin-top: 20px; }
            .card { border: 1px solid #ddd; border-radius: 4px; padding: 15px; margin-bottom: 20px; }
            .card-header { background-color: #f8f9fa; padding: 10px; margin: -15px -15px 15px; border-bottom: 1px solid #ddd; }
            .status-ok { color: green; }
            .status-warning { color: orange; }
            .status-error { color: red; }
            .error-list { background-color: #f8d7da; border: 1px solid #f5c6cb; border-radius: 4px; padding: 10px; }
            pre { background-color: #f8f9fa; padding: 10px; border-radius: 4px; overflow: auto; }
            table { width: 100%; border-collapse: collapse; }
            table, th, td { border: 1px solid #ddd; }
            th, td { padding: 8px; text-align: left; }
            th { background-color: #f8f9fa; }
        </style>
    </head>
    <body>
        <h1>Application Diagnostics</h1>
        
        <div class="card">
            <div class="card-header">
                <h2>Overview</h2>
            </div>
            <p><strong>Initialized:</strong> 
                <span class="{{ 'status-ok' if init_status.initialized else 'status-error' }}">
                    {{ 'Yes' if init_status.initialized else 'No' }}
                </span>
            </p>
            <p><strong>Uptime:</strong> {{ init_status.uptime }} seconds</p>
            <p><strong>Python Version:</strong> {{ init_status.python.version }}</p>
            <p><strong>Database Status:</strong> 
                <span class="
                    {{ 'status-ok' if init_status.database.status == 'connected' else 
                       'status-warning' if init_status.database.status == 'missing' else 
                       'status-error' }}">
                    {{ init_status.database.status }}
                </span>
                {% if init_status.database.message %}
                <br><em>{{ init_status.database.message }}</em>
                {% endif %}
            </p>
        </div>
        
        {% if init_status.errors %}
        <div class="card">
            <div class="card-header">
                <h2>Errors</h2>
            </div>
            <div class="error-list">
                <ul>
                {% for error in init_status.errors %}
                    <li>{{ error }}</li>
                {% endfor %}
                </ul>
            </div>
        </div>
        {% endif %}
        
        <div class="card">
            <div class="card-header">
                <h2>Modules</h2>
            </div>
            <table>
                <tr>
                    <th>Module</th>
                    <th>Loaded</th>
                    <th>Initialized</th>
                    <th>Path</th>
                    <th>Error</th>
                </tr>
                {% for name, info in init_status.modules.items() %}
                <tr>
                    <td>{{ name }}</td>
                    <td class="{{ 'status-ok' if info.loaded else 'status-error' }}">
                        {{ 'Yes' if info.loaded else 'No' }}
                    </td>
                    <td class="{{ 'status-ok' if info.initialized else 'status-error' }}">
                        {{ 'Yes' if info.initialized else 'No' }}
                    </td>
                    <td>{{ info.path }}</td>
                    <td class="{{ 'status-error' if info.error else '' }}">{{ info.error or '' }}</td>
                </tr>
                {% endfor %}
            </table>
        </div>
        
        <div class="card">
            <div class="card-header">
                <h2>Database</h2>
            </div>
            <p><strong>Path:</strong> {{ init_status.database.path }}</p>
            <p><strong>Status:</strong> {{ init_status.database.status }}</p>
            
            {% if init_status.database.tables %}
            <h3>Tables</h3>
            <ul>
                {% for table in init_status.database.tables %}
                <li>{{ table }}</li>
                {% endfor %}
            </ul>
            {% else %}
            <p>No tables found in database.</p>
            {% endif %}
        </div>
        
        <div class="card">
            <div class="card-header">
                <h2>File Permissions</h2>
            </div>
            <table>
                <tr>
                    <th>Path</th>
                    <th>Exists</th>
                    <th>Writable</th>
                    <th>Issues</th>
                </tr>
                {% for path, info in init_status.file_permissions.items() %}
                <tr>
                    <td>{{ path }}</td>
                    <td class="{{ 'status-ok' if info.exists == True else 'status-error' }}">
                        {{ 'Yes' if info.exists == True else 'No' }}
                    </td>
                    <td class="{{ 'status-ok' if info.get('writable', False) else 'status-error' }}">
                        {{ 'Yes' if info.get('writable', False) else 'No' }}
                    </td>
                    <td class="{{ 'status-error' if info.get('error') else '' }}">
                        {{ info.get('error', '') }}
                    </td>
                </tr>
                {% endfor %}
            </table>
        </div>
        
        <div class="card">
            <div class="card-header">
                <h2>Environment</h2>
            </div>
            <table>
                <tr>
                    <th>Key</th>
                    <th>Value</th>
                </tr>
                {% for key, value in init_status.environment.items() %}
                <tr>
                    <td>{{ key }}</td>
                    <td>{{ value }}</td>
                </tr>
                {% endfor %}
            </table>
        </div>
        
        <div class="card">
            <div class="card-header">
                <h2>Actions</h2>
            </div>
            <p>Here are some actions you can take to fix common issues:</p>
            <ul>
                <li><a href="/diagnostic/fix-database">Attempt to fix database issues</a></li>
                <li><a href="/diagnostic/fix-permissions">Fix file permissions</a></li>
                <li><a href="/diagnostic/initialize-templates">Initialize templates</a></li>
                <li><a href="/diagnostic/reload-modules">Force module reload</a></li>
            </ul>
        </div>
        
    </body>
    </html>
    """, init_status=init_status)

@diagnostic_bp.route('/fix-database')
def fix_database():
    """Attempt to fix database issues."""
    try:
        db_path = current_app.config.get('DATABASE_PATH', '/app/data/malware_platform.db')
        db_dir = os.path.dirname(db_path)
        
        # Create database directory if it doesn't exist
        if not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        
        if not os.path.exists(db_path):
            # Initialize database from scratch
            try:
                from database import init_db
                with current_app.app_context():
                    init_db()
                return jsonify({
                    'status': 'success',
                    'message': 'Database initialized successfully'
                })
            except Exception as e:
                return jsonify({
                    'status': 'error',
                    'message': f'Failed to initialize database: {str(e)}',
                    'traceback': traceback.format_exc()
                })
        else:
            # Check database schema
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                # Check for core tables
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [table[0] for table in cursor.fetchall()]
                
                # If key tables are missing, try to reinitialize
                required_tables = ['users', 'malware_samples', 'detonation_jobs']
                missing_tables = [table for table in required_tables if table not in tables]
                
                if missing_tables:
                    from database import init_db
                    with current_app.app_context():
                        init_db()
                        
                    return jsonify({
                        'status': 'success',
                        'message': f'Database schema updated, added missing tables: {", ".join(missing_tables)}'
                    })
                else:
                    return jsonify({
                        'status': 'success',
                        'message': 'Database schema appears to be correct'
                    })
            except Exception as e:
                return jsonify({
                    'status': 'error',
                    'message': f'Error checking database schema: {str(e)}',
                    'traceback': traceback.format_exc()
                })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Unexpected error: {str(e)}',
            'traceback': traceback.format_exc()
        })

@diagnostic_bp.route('/fix-permissions')
def fix_permissions():
    """Fix file permissions."""
    try:
        paths = [
            '/app/data',
            '/app/data/uploads',
            '/app/data/database',
            '/app/static',
            '/app/static/css',
            '/app/static/js',
            '/app/templates'
        ]
        
        results = {}
        
        for path in paths:
            try:
                if not os.path.exists(path):
                    os.makedirs(path, exist_ok=True)
                    results[path] = {
                        'created': True,
                        'chmod': False
                    }
                
                # Set permissions (755 = rwxr-xr-x)
                os.chmod(path, 0o755)
                results[path] = {
                    'created': False,
                    'chmod': True
                }
                
                # Create a test file to verify write permissions
                test_file = os.path.join(path, '.permissions_test')
                with open(test_file, 'w') as f:
                    f.write('test')
                os.remove(test_file)
                results[path]['writable'] = True
                
            except Exception as e:
                results[path] = {
                    'error': str(e)
                }
        
        return jsonify({
            'status': 'success',
            'message': 'Permission fix attempted',
            'results': results
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Unexpected error: {str(e)}',
            'traceback': traceback.format_exc()
        })

@diagnostic_bp.route('/initialize-templates')
def initialize_templates():
    """Force template generation."""
    try:
        results = {}
        
        # Generate base templates from web_interface
        try:
            from web_interface import generate_base_templates
            with current_app.app_context():
                generate_base_templates()
            results['base_templates'] = {
                'status': 'success'
            }
        except Exception as e:
            results['base_templates'] = {
                'status': 'error',
                'error': str(e)
            }
        
        # Generate module-specific templates
        for module_name in ['malware', 'detonation', 'viz']:
            try:
                module = importlib.import_module(f"{module_name}_module")
                if hasattr(module, 'generate_templates'):
                    with current_app.app_context():
                        module.generate_templates()
                    results[f"{module_name}_templates"] = {
                        'status': 'success'
                    }
                else:
                    results[f"{module_name}_templates"] = {
                        'status': 'warning',
                        'message': 'No generate_templates function found'
                    }
            except Exception as e:
                results[f"{module_name}_templates"] = {
                    'status': 'error',
                    'error': str(e)
                }
        
        # Create minimal index.html if it doesn't exist
        try:
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
            <li><a href="/diagnostic">Diagnostics</a></li>
        </ul>
    </div>
</body>
</html>""")
                results['index_html'] = {
                    'status': 'success',
                    'message': 'Created index.html'
                }
            else:
                results['index_html'] = {
                    'status': 'success',
                    'message': 'index.html already exists'
                }
        except Exception as e:
            results['index_html'] = {
                'status': 'error',
                'error': str(e)
            }
        
        return jsonify({
            'status': 'success',
            'message': 'Templates initialization attempted',
            'results': results
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Unexpected error: {str(e)}',
            'traceback': traceback.format_exc()
        })

@diagnostic_bp.route('/reload-modules')
def reload_modules():
    """Force module reload."""
    try:
        from main import MODULES
        
        results = {}
        
        for name, module_path in MODULES.items():
            try:
                # Remove the module from sys.modules if it exists
                if module_path in sys.modules:
                    del sys.modules[module_path]
                
                # Re-import the module
                module = importlib.import_module(module_path)
                
                # Try to initialize if it has init_app
                if hasattr(module, 'init_app'):
                    with current_app.app_context():
                        module.init_app(current_app)
                    
                results[name] = {
                    'status': 'success',
                    'reloaded': True,
                    'initialized': hasattr(module, 'init_app')
                }
            except Exception as e:
                results[name] = {
                    'status': 'error',
                    'error': str(e),
                    'traceback': traceback.format_exc()
                }
        
        return jsonify({
            'status': 'success',
            'message': 'Module reload attempted',
            'results': results
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Unexpected error: {str(e)}',
            'traceback': traceback.format_exc()
        })

@diagnostic_bp.route('/api/status')
def api_status():
    """Return diagnostic information as JSON."""
    # Capture current state
    try:
        capture_environment()
        capture_module_info()
        check_database()
        check_file_permissions()
    except Exception as e:
        init_status['errors'].append(f"Error capturing diagnostic info: {str(e)}")
    
    # Update initialization status
    init_status['initialized'] = True
    init_status['uptime'] = time.time() - init_status['start_time']
    
    return jsonify(init_status)

def init_app(app):
    """Initialize the diagnostic module."""
    # Register blueprint early
    try:
        app.register_blueprint(diagnostic_bp)
        logger.info("Diagnostic blueprint registered successfully")
        
        # Mark initialization
        init_status['start_time'] = time.time()
        
        return True
    except Exception as e:
        logger.error(f"Error registering diagnostic blueprint: {e}")
        init_status['errors'].append(f"Blueprint registration error: {str(e)}")
        return False
