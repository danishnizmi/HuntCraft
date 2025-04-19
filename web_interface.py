from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, g, jsonify, session, abort
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import sqlite3
import json
import os
import datetime
import logging
import traceback
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Create blueprint - Root path is handled by this blueprint
web_bp = Blueprint('web', __name__)
login_manager = LoginManager()

class User(UserMixin):
    def __init__(self, id, username, role):
        self.id = id
        self.username = username
        self.role = role

def init_app(app):
    """Initialize web interface module with Flask app"""
    logger.info("Initializing web interface module")
    
    # Register blueprint first to avoid initialization issues
    try:
        app.register_blueprint(web_bp)
        logger.info("Web interface blueprint registered successfully")
    except Exception as e:
        logger.error(f"Failed to register web interface blueprint: {e}")
        raise
    
    # Continue with other initialization in a safer way
    try:
        # Set up exception handling
        app.errorhandler(500)(handle_server_error)
        app.errorhandler(Exception)(handle_exception)
        
        # Setup login manager
        login_manager.init_app(app)
        login_manager.login_view = 'web.login'
        login_manager.login_message = "Please log in to access this page."
        login_manager.login_message_category = "info"
        
        # Set up context processor for common template variables
        app.context_processor(inject_template_variables)
        
        # Generate necessary templates and static files
        with app.app_context():
            # Ensure necessary directories exist
            ensure_directories(app)
            
            # Ensure the database has been initialized with the user table
            ensure_db_tables(app)
            
            # Generate templates
            generate_base_templates()
            
            # Generate basic CSS and JS
            generate_static_files()
            
            logger.info("Web interface module initialized successfully")
    except Exception as e:
        logger.error(f"Error in web interface module initialization: {e}\n{traceback.format_exc()}")
        # Don't re-raise to allow app to start with limited functionality

def ensure_directories(app):
    """Ensure all required directories exist"""
    dirs_to_create = [
        app.template_folder,
        app.static_folder,
        os.path.join(app.static_folder, 'css'),
        os.path.join(app.static_folder, 'js'),
        os.path.dirname(app.config.get('DATABASE_PATH', '/app/data/malware_platform.db')),
        app.config.get('UPLOAD_FOLDER', '/app/data/uploads')
    ]
    
    for directory in dirs_to_create:
        try:
            os.makedirs(directory, exist_ok=True)
            logger.info(f"Ensured directory exists: {directory}")
        except Exception as e:
            logger.error(f"Error creating directory {directory}: {e}")

def handle_server_error(e):
    """Handle 500 errors gracefully"""
    error_traceback = traceback.format_exc()
    logger.error(f"Server error: {str(e)}\n{error_traceback}")
    if current_app.config.get('DEBUG', False):
        # Show detailed error information in debug mode
        return render_template('error.html', 
                              error_code=500,
                              error_message=f"Server error: {str(e)}",
                              error_details=error_traceback), 500
    else:
        return render_template('error.html', 
                              error_code=500,
                              error_message="The server encountered an internal error. Please try again later."), 500

def handle_exception(e):
    """Handle uncaught exceptions"""
    error_traceback = traceback.format_exc()
    logger.error(f"Uncaught exception: {str(e)}\n{error_traceback}")
    if current_app.config.get('DEBUG', False):
        # Show detailed error information in debug mode
        return render_template('error.html', 
                              error_code=500,
                              error_message=f"Uncaught exception: {str(e)}",
                              error_details=error_traceback), 500
    else:
        return render_template('error.html', 
                              error_code=500,
                              error_message="The server encountered an internal error. Please try again later."), 500

def inject_template_variables():
    """Inject common variables into all templates"""
    return {
        'app_name': current_app.config.get('APP_NAME', 'Malware Detonation Platform'),
        'year': datetime.datetime.now().year,
        'colors': {
            'primary': current_app.config.get('PRIMARY_COLOR', '#4a6fa5'),
            'secondary': current_app.config.get('SECONDARY_COLOR', '#6c757d'),
            'danger': current_app.config.get('DANGER_COLOR', '#dc3545'),
            'success': current_app.config.get('SUCCESS_COLOR', '#28a745'),
            'warning': current_app.config.get('WARNING_COLOR', '#ffc107'),
            'info': current_app.config.get('INFO_COLOR', '#17a2b8'),
            'dark': current_app.config.get('DARK_COLOR', '#343a40'),
            'light': current_app.config.get('LIGHT_COLOR', '#f8f9fa')
        }
    }

@login_manager.user_loader
def load_user(user_id):
    """Load user by ID for Flask-Login"""
    try:
        conn = _db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, role FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        conn.close()
        
        if user:
            return User(user[0], user[1], user[2])
    except Exception as e:
        logger.error(f"Error loading user: {e}")
    return None

def ensure_db_tables(app):
    """Ensure database tables exist and admin user is created"""
    logger.info("Checking and initializing database tables")
    try:
        # Check if the database file exists
        db_path = app.config.get('DATABASE_PATH')
        db_dir = os.path.dirname(db_path)
        
        if not os.path.exists(db_dir):
            logger.info(f"Database directory doesn't exist at {db_dir}, creating it")
            os.makedirs(db_dir, exist_ok=True)
        
        if not os.path.exists(db_path):
            logger.info(f"Database file doesn't exist at {db_path}, creating it")
        
        # Connect to database
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if users table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        table_exists = cursor.fetchone() is not None
        
        if not table_exists:
            logger.info("Users table doesn't exist, creating it")
            # Create users table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            
            # Create default admin user
            cursor.execute(
                "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                ("admin", generate_password_hash("admin123"), "admin")
            )
            logger.info("Created default admin user")
        else:
            # Check if admin user exists
            cursor.execute("SELECT COUNT(*) FROM users WHERE username = 'admin'")
            admin_exists = cursor.fetchone()[0] > 0
            
            if not admin_exists:
                logger.info("Admin user doesn't exist, creating it")
                cursor.execute(
                    "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                    ("admin", generate_password_hash("admin123"), "admin")
                )
        
        conn.commit()
        conn.close()
        logger.info("Database tables initialization complete")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        # Log detailed traceback but don't crash the app
        logger.error(traceback.format_exc())

def create_database_schema(cursor):
    """Create database tables"""
    try:
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        # Create default admin user if no users exist
        cursor.execute("SELECT COUNT(*) FROM users")
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                ("admin", generate_password_hash("admin123"), "admin")
            )
            logger.info("Created default admin user")
        
        logger.info("Web interface database schema created successfully")
    except Exception as e:
        logger.error(f"Error creating web interface database schema: {e}")
        raise

def _db_connection(row_factory=None):
    """Create a database connection with optional row factory"""
    try:
        db_path = current_app.config.get('DATABASE_PATH')
        # Ensure the directory exists
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        conn = sqlite3.connect(db_path)
        if row_factory:
            conn.row_factory = row_factory
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        raise

def admin_required(f):
    """Decorator to require admin role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('You need admin privileges to access this page', 'danger')
            return redirect(url_for('web.index'))
        return f(*args, **kwargs)
    return decorated_function

# Root route handler - Main entry point for the application
@web_bp.route('/')
def index():
    """Home page"""
    logger.info("Web blueprint index route handler called")
    try:
        # Render the template
        return render_template('index.html')
    except Exception as e:
        error_details = traceback.format_exc()
        logger.error(f"Error rendering index page: {str(e)}\nTraceback: {error_details}")
        
        # Fallback to a minimal response if template rendering fails
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Malware Detonation Platform</title>
            <style>
                body {{ font-family: Arial, sans-serif; text-align: center; margin-top: 50px; }}
                h1 {{ color: #4a6fa5; }}
                .links {{ margin-top: 20px; }}
                .links a {{ display: inline-block; margin: 0 10px; padding: 8px 15px; 
                          color: white; background-color: #4a6fa5; text-decoration: none; 
                          border-radius: 4px; }}
                .links a:hover {{ background-color: #395d89; }}
                .alert {{ background-color: #f8d7da; color: #721c24; padding: 10px; 
                        border-radius: 4px; margin-bottom: 20px; }}
            </style>
        </head>
        <body>
            <h1>Malware Detonation Platform</h1>
            <p>Welcome to the platform.</p>
            <div class="alert">
                <strong>Warning:</strong> Template rendering failed. Using fallback interface.
            </div>
            <div class="links">
                <a href="/malware">Malware Analysis</a>
                <a href="/detonation">Detonation Service</a>
                <a href="/viz">Visualizations</a>
                <a href="/diagnostic">System Diagnostics</a>
            </div>
        </body>
        </html>
        """

@web_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Login page"""
    # Redirect if already logged in
    if current_user.is_authenticated:
        return redirect(url_for('web.dashboard'))
        
    error = None
    if request.method == 'POST':
        try:
            username = request.form.get('username')
            password = request.form.get('password')
            remember = 'remember' in request.form
            
            # Ensure database exists before trying to login
            db_path = current_app.config.get('DATABASE_PATH')
            db_dir = os.path.dirname(db_path)
            
            if not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)
                
            if not os.path.exists(db_path):
                logger.warning(f"Database file not found at {db_path}, initializing it")
                ensure_db_tables(current_app)
            
            conn = _db_connection()
            cursor = conn.cursor()
            
            # Check if users table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
            if cursor.fetchone() is None:
                logger.warning("Users table doesn't exist, creating it")
                create_database_schema(cursor)
                conn.commit()
            
            cursor.execute("SELECT id, username, password, role FROM users WHERE username = ?", (username,))
            user_data = cursor.fetchone()
            conn.close()
            
            if user_data and check_password_hash(user_data[2], password):
                user = User(user_data[0], user_data[1], user_data[3])
                login_user(user, remember=remember)
                
                # Redirect to the original requested page or dashboard
                next_page = request.args.get('next')
                if not next_page or not next_page.startswith('/'):
                    next_page = url_for('web.dashboard')
                return redirect(next_page)
            
            # Debug output when login fails
            if user_data:
                logger.warning(f"Login failed for user {username}: Password hash verification failed")
            else:
                logger.warning(f"Login failed for user {username}: User not found")
                
            error = 'Invalid username or password'
        except Exception as e:
            logger.error(f"Login error: {e}")
            error = 'An error occurred during login. Please try again.'
    
    try:
        return render_template('login.html', error=error)
    except Exception as e:
        logger.error(f"Error rendering login template: {e}")
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Login - Malware Detonation Platform</title>
            <style>
                body {{ font-family: Arial, sans-serif; text-align: center; margin-top: 50px; }}
                .login-form {{ max-width: 400px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 5px; }}
                h1 {{ color: #4a6fa5; }}
                input {{ width: 100%; padding: 8px; margin-bottom: 10px; }}
                button {{ padding: 10px 15px; background-color: #4a6fa5; color: white; border: none; cursor: pointer; }}
                .error {{ color: #dc3545; margin-bottom: 15px; }}
            </style>
        </head>
        <body>
            <h1>Malware Detonation Platform</h1>
            <div class="login-form">
                <h2>Login</h2>
                {{'<div class="error">' + error + '</div>' if error else ''}}
                <form method="POST">
                    <div>
                        <input type="text" id="username" name="username" placeholder="Username" required>
                    </div>
                    <div>
                        <input type="password" id="password" name="password" placeholder="Password" required>
                    </div>
                    <div>
                        <label>
                            <input type="checkbox" name="remember"> Remember me
                        </label>
                    </div>
                    <button type="submit">Login</button>
                </form>
                <p><small>Default credentials: admin / admin123</small></p>
            </div>
        </body>
        </html>
        """

@web_bp.route('/logout')
@login_required
def logout():
    """Logout user"""
    logout_user()
    flash('You have been logged out', 'success')
    return redirect(url_for('web.index'))

@web_bp.route('/dashboard')
@login_required
def dashboard():
    """Dashboard page"""
    # Get recent data
    datasets = []
    analyses = []
    visualizations = []
    
    try:
        # Safe import of modules using try/except
        try:
            from main import get_module
            malware_module = get_module('malware')
            if malware_module and hasattr(malware_module, 'get_datasets'):
                datasets = malware_module.get_datasets()
            elif malware_module and hasattr(malware_module, 'get_recent_samples'):
                # Alternative function name
                datasets = malware_module.get_recent_samples(5)
            else:
                logger.warning("Malware module or dataset functions not available")
        except Exception as e:
            logger.error(f"Error loading recent samples: {e}")
        
        try:
            from main import get_module
            detonation_module = get_module('detonation')
            if detonation_module and hasattr(detonation_module, 'get_detonation_jobs'):
                analyses = detonation_module.get_detonation_jobs()[:5] if hasattr(detonation_module.get_detonation_jobs(), '__len__') and len(detonation_module.get_detonation_jobs()) > 0 else []
            else:
                logger.warning("Detonation module or get_detonation_jobs function not available")
        except Exception as e:
            logger.error(f"Error loading detonation jobs: {e}")
        
        try:
            from main import get_module
            viz_module = get_module('viz')
            if viz_module and hasattr(viz_module, 'get_visualizations_for_dashboard'):
                visualizations = viz_module.get_visualizations_for_dashboard()
            else:
                logger.warning("Visualization module or get_visualizations_for_dashboard function not available")
        except Exception as e:
            logger.error(f"Error loading visualizations: {e}")
    except Exception as e:
        logger.error(f"Dashboard data loading error: {e}")
    
    try:
        return render_template('dashboard.html', 
                            datasets=datasets, 
                            analyses=analyses,
                            visualizations=visualizations)
    except Exception as e:
        logger.error(f"Error rendering dashboard template: {e}")
        return redirect(url_for('web.index'))

@web_bp.route('/profile')
@login_required
def profile():
    """User profile page"""
    try:
        return render_template('profile.html')
    except Exception as e:
        logger.error(f"Error rendering profile template: {e}")
        return redirect(url_for('web.dashboard'))

@web_bp.route('/users')
@login_required
@admin_required
def users():
    """User management page - admin only"""
    try:
        conn = _db_connection(sqlite3.Row)
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, role, created_at FROM users ORDER BY id")
        users_list = [dict(row) for row in cursor.fetchall()]
        conn.close()
    except Exception as e:
        logger.error(f"Error fetching users: {e}")
        users_list = []
        flash("Error loading users", "danger")
    
    try:
        return render_template('users.html', users=users_list)
    except Exception as e:
        logger.error(f"Error rendering users template: {e}")
        return redirect(url_for('web.dashboard'))

# Admin route placeholder to satisfy urls used in templates
@web_bp.route('/infrastructure')
@login_required
@admin_required
def infrastructure():
    return redirect(url_for('web.diagnostic'))

# Admin route placeholder to satisfy urls used in templates
@web_bp.route('/add_user')
@login_required
@admin_required
def add_user():
    flash("User management functionality is not fully implemented yet.", "info")
    return redirect(url_for('web.users'))

@web_bp.route('/health')
def health_check():
    """Health check endpoint"""
    # Check database health
    try:
        conn = _db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        conn.close()
        
        db_status = {
            "status": "healthy",
            "users_table": True,
            "user_count": user_count
        }
    except Exception as e:
        db_status = {
            "status": "unhealthy", 
            "error": str(e)
        }
    
    # Check template directory
    template_status = {
        "status": "unknown"
    }
    try:
        template_dir = current_app.template_folder
        template_status = {
            "status": "healthy" if os.path.exists(template_dir) else "unhealthy",
            "path": template_dir,
            "exists": os.path.exists(template_dir),
            "files": os.listdir(template_dir) if os.path.exists(template_dir) else []
        }
    except Exception as e:
        template_status = {
            "status": "unhealthy",
            "error": str(e)
        }
    
    return jsonify({
        "status": "healthy" if db_status["status"] == "healthy" and template_status["status"] == "healthy" else "degraded",
        "source": "web_blueprint", 
        "database": db_status,
        "templates": template_status,
        "timestamp": datetime.datetime.now().isoformat()
    })

@web_bp.route('/diagnostic')
def diagnostic():
    """Diagnostic page with system information"""
    diagnostics = {
        'app_info': {
            'app_name': current_app.config.get('APP_NAME', 'Malware Detonation Platform'),
            'debug_mode': current_app.config.get('DEBUG', False),
            'templates_path': current_app.template_folder,
            'static_path': current_app.static_folder,
        },
        'module_status': {},
        'template_info': {},
        'database_info': {},
        'route_info': {}
    }
    
    # Check module status
    try:
        from main import module_status
        diagnostics['module_status'] = module_status
    except ImportError:
        diagnostics['module_status'] = {'error': 'Could not import module_status from main'}
    
    # Check template files
    try:
        template_dir = current_app.template_folder
        if not os.path.isabs(template_dir):
            template_dir = os.path.join(current_app.root_path, template_dir)
        
        diagnostics['template_info']['path'] = template_dir
        diagnostics['template_info']['exists'] = os.path.exists(template_dir)
        
        if diagnostics['template_info']['exists']:
            templates = os.listdir(template_dir)
            diagnostics['template_info']['files'] = templates
            diagnostics['template_info']['base_exists'] = 'base.html' in templates
            diagnostics['template_info']['index_exists'] = 'index.html' in templates
            
            # Check template sizes
            if diagnostics['template_info']['base_exists']:
                base_path = os.path.join(template_dir, 'base.html')
                diagnostics['template_info']['base_size'] = os.path.getsize(base_path)
            
            if diagnostics['template_info']['index_exists']:
                index_path = os.path.join(template_dir, 'index.html')
                diagnostics['template_info']['index_size'] = os.path.getsize(index_path)
    except Exception as e:
        diagnostics['template_info']['error'] = str(e)
    
    # Check database
    try:
        db_path = current_app.config.get('DATABASE_PATH')
        diagnostics['database_info']['path'] = db_path
        diagnostics['database_info']['exists'] = os.path.exists(db_path)
        
        if diagnostics['database_info']['exists']:
            conn = _db_connection()
            cursor = conn.cursor()
            
            # Check users table
            cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='users'")
            diagnostics['database_info']['users_table_exists'] = cursor.fetchone()[0] > 0
            
            # Check user count
            if diagnostics['database_info']['users_table_exists']:
                cursor.execute("SELECT COUNT(*) FROM users")
                diagnostics['database_info']['user_count'] = cursor.fetchone()[0]
                
                # Check admin user
                cursor.execute("SELECT COUNT(*) FROM users WHERE username='admin'")
                diagnostics['database_info']['admin_user_exists'] = cursor.fetchone()[0] > 0
            
            conn.close()
    except Exception as e:
        diagnostics['database_info']['error'] = str(e)
    
    # Get route info
    try:
        routes = []
        for rule in current_app.url_map.iter_rules():
            routes.append({
                'endpoint': rule.endpoint,
                'methods': list(rule.methods),
                'path': str(rule)
            })
        diagnostics['route_info']['routes'] = routes
        
        # Count routes by blueprint
        blueprint_routes = {}
        for route in routes:
            bp_name = route['endpoint'].split('.')[0] if '.' in route['endpoint'] else 'app'
            if bp_name not in blueprint_routes:
                blueprint_routes[bp_name] = 0
            blueprint_routes[bp_name] += 1
        
        diagnostics['route_info']['blueprint_routes'] = blueprint_routes
    except Exception as e:
        diagnostics['route_info']['error'] = str(e)
    
    try:
        return render_template('diagnostic.html', diagnostics=diagnostics)
    except Exception as e:
        logger.error(f"Error rendering diagnostic template: {e}")
        # Return JSON response if template fails
        return jsonify(diagnostics)

@web_bp.route('/recreate-templates', methods=['POST'])
def recreate_templates():
    """Recreate basic templates endpoint"""
    try:
        generate_base_templates()
        generate_static_files()
        return jsonify({"success": True, "message": "Templates recreated successfully"})
    except Exception as e:
        logger.error(f"Error recreating templates: {e}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500

@web_bp.route('/init-database', methods=['POST'])
def initialize_database():
    """Initialize database endpoint"""
    try:
        ensure_db_tables(current_app)
        return jsonify({"success": True, "message": "Database initialized successfully"})
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500

# Generate static files for CSS and JS
def generate_static_files():
    """Generate CSS and JS files if they don't exist"""
    # CSS file
    css_path = os.path.join(current_app.static_folder, 'css', 'main.css')
    os.makedirs(os.path.dirname(css_path), exist_ok=True)
    
    if not os.path.exists(css_path):
        try:
            with open(css_path, 'w') as f:
                f.write("""/* Main CSS styles */
body { 
    font-family: 'Helvetica Neue', Arial, sans-serif; 
    line-height: 1.6; 
    color: #333; 
    background-color: #f8f9fa; 
}
.card { 
    box-shadow: 0 2px 4px rgba(0,0,0,0.05); 
    margin-bottom: 20px; 
    border: none; 
    border-radius: 8px; 
}
.card-header { 
    border-top-left-radius: 8px !important; 
    border-top-right-radius: 8px !important; 
}
.hash-value { 
    font-family: monospace; 
    word-break: break-all; 
}
.table-responsive { 
    overflow-x: auto; 
}
footer { 
    margin-top: 50px; 
    padding: 20px 0; 
    border-top: 1px solid #e9ecef; 
}

/* Enhanced error styles */
pre {
    background-color: #f8f9fa;
    padding: 10px;
    border-radius: 4px;
    border: 1px solid #dee2e6;
    white-space: pre-wrap;
    word-wrap: break-word;
    max-height: 300px;
    overflow-y: auto;
}
""")
            logger.info("Created main CSS file")
        except Exception as e:
            logger.error(f"Error creating CSS file: {e}")
    
    # JS file
    js_path = os.path.join(current_app.static_folder, 'js', 'main.js')
    os.makedirs(os.path.dirname(js_path), exist_ok=True)
    
    if not os.path.exists(js_path):
        try:
            with open(js_path, 'w') as f:
                f.write("""// Main JavaScript
document.addEventListener('DOMContentLoaded', function() {
    // Handle delete confirmations
    const confirmButtons = document.querySelectorAll('[data-confirm]');
    if (confirmButtons) {
        confirmButtons.forEach(button => {
            button.addEventListener('click', function(e) {
                if (!confirm(this.getAttribute('data-confirm') || 'Are you sure?')) {
                    e.preventDefault();
                }
            });
        });
    }
    
    // Auto-hide alerts after 5 seconds
    const alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
    if (alerts) {
        alerts.forEach(alert => {
            setTimeout(function() {
                alert.classList.add('fade');
                setTimeout(function() { alert.remove(); }, 500);
            }, 5000);
        });
    }
});
""")
            logger.info("Created main JS file")
        except Exception as e:
            logger.error(f"Error creating JS file: {e}")

# Template generation
def generate_base_templates():
    """Generate essential HTML templates for the application"""
    templates_to_generate = {
        'base.html': """<!DOCTYPE html>
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
        .navbar { background-color: {{ colors.primary }} !important; }
        .btn-primary { background-color: {{ colors.primary }}; border-color: {{ colors.primary }}; }
        .btn-primary:hover { background-color: {{ colors.primary }}; filter: brightness(90%); }
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
            <p>&copy; {{ year }} {{ app_name }}</p>
        </div>
    </footer>

    <!-- Bootstrap JS Bundle with Popper -->
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    
    <!-- Custom JS -->
    <script src="{{ url_for('static', filename='js/main.js') }}"></script>
    {% block scripts %}{% endblock %}
</body>
</html>""",
        
        'index.html': """{% extends 'base.html' %}

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
{% endblock %}""",
        
        'login.html': """{% extends 'base.html' %}

{% block title %}Login - {{ app_name }}{% endblock %}

{% block content %}
<div class="row justify-content-center">
    <div class="col-md-6">
        <div class="card">
            <div class="card-header bg-primary text-white">
                <h3 class="card-title mb-0">Login</h3>
            </div>
            <div class="card-body">
                {% if error %}
                <div class="alert alert-danger">{{ error }}</div>
                {% endif %}
                
                <form method="POST">
                    <div class="mb-3">
                        <label for="username" class="form-label">Username</label>
                        <input type="text" class="form-control" id="username" name="username" required>
                    </div>
                    <div class="mb-3">
                        <label for="password" class="form-label">Password</label>
                        <input type="password" class="form-control" id="password" name="password" required>
                    </div>
                    <div class="mb-3 form-check">
                        <input type="checkbox" class="form-check-input" id="remember" name="remember">
                        <label class="form-check-label" for="remember">Remember me</label>
                    </div>
                    <button type="submit" class="btn btn-primary">Login</button>
                </form>
                
                <div class="mt-4">
                    <small class="text-muted">Default credentials: admin / admin123</small>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}""",
        
        'error.html': """{% extends 'base.html' %}

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
{% endblock %}""",

        'profile.html': """{% extends 'base.html' %}

{% block title %}User Profile - {{ app_name }}{% endblock %}

{% block content %}
<div class="row">
    <div class="col-md-8 mx-auto">
        <div class="card">
            <div class="card-header bg-primary text-white">
                <h2 class="card-title">User Profile</h2>
            </div>
            <div class="card-body">
                <div class="row mb-4">
                    <div class="col-md-4 text-center">
                        <i class="fas fa-user-circle fa-6x text-secondary"></i>
                    </div>
                    <div class="col-md-8">
                        <h3>{{ current_user.username }}</h3>
                        <p><strong>Role:</strong> {{ current_user.role }}</p>
                        <p><strong>ID:</strong> {{ current_user.id }}</p>
                    </div>
                </div>
                
                <div class="mb-4">
                    <h4>Account Settings</h4>
                    <p>
                        <a href="#" class="btn btn-outline-primary">
                            <i class="fas fa-key"></i> Change Password
                        </a>
                    </p>
                </div>
                
                <div class="mb-4">
                    <h4>Activity</h4>
                    <p>Recent activity will be shown here in future versions.</p>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}""",

        'users.html': """{% extends 'base.html' %}

{% block title %}User Management - {{ app_name }}{% endblock %}

{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4">
    <h1>User Management</h1>
    <a href="{{ url_for('web.add_user') }}" class="btn btn-primary">
        <i class="fas fa-user-plus"></i> Add User
    </a>
</div>

{% if users %}
    <div class="card">
        <div class="card-header bg-primary text-white">
            <h5 class="card-title mb-0">Users</h5>
        </div>
        <div class="card-body">
            <div class="table-responsive">
                <table class="table table-hover">
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Username</th>
                            <th>Role</th>
                            <th>Created</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for user in users %}
                        <tr>
                            <td>{{ user.id }}</td>
                            <td>{{ user.username }}</td>
                            <td>{{ user.role }}</td>
                            <td>{{ user.created_at }}</td>
                            <td>
                                <a href="#" class="btn btn-sm btn-info">
                                    <i class="fas fa-edit"></i>
                                </a>
                                {% if user.username != 'admin' %}
                                <a href="#" class="btn btn-sm btn-danger" data-confirm="Are you sure you want to delete this user?">
                                    <i class="fas fa-trash"></i>
                                </a>
                                {% endif %}
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
{% else %}
    <div class="alert alert-warning">
        <i class="fas fa-exclamation-triangle"></i> No users found.
    </div>
{% endif %}
{% endblock %}""",

        'diagnostic.html': """{% extends 'base.html' %}

{% block title %}System Diagnostics - {{ app_name }}{% endblock %}

{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4">
    <h1>System Diagnostics</h1>
    <div>
        <button id="recreate-templates-btn" class="btn btn-warning">
            <i class="fas fa-sync"></i> Recreate Templates
        </button>
        <button id="init-database-btn" class="btn btn-danger">
            <i class="fas fa-database"></i> Initialize Database
        </button>
    </div>
</div>

<div class="row">
    <!-- Application Info -->
    <div class="col-md-6 mb-4">
        <div class="card">
            <div class="card-header bg-primary text-white">
                <h5 class="card-title mb-0">Application Information</h5>
            </div>
            <div class="card-body">
                <table class="table table-sm">
                    <tr>
                        <th>Application Name:</th>
                        <td>{{ diagnostics.app_info.app_name }}</td>
                    </tr>
                    <tr>
                        <th>Debug Mode:</th>
                        <td>{{ diagnostics.app_info.debug_mode }}</td>
                    </tr>
                    <tr>
                        <th>Templates Path:</th>
                        <td>{{ diagnostics.app_info.templates_path }}</td>
                    </tr>
                    <tr>
                        <th>Static Path:</th>
                        <td>{{ diagnostics.app_info.static_path }}</td>
                    </tr>
                </table>
            </div>
        </div>
    </div>
    
    <!-- Module Status -->
    <div class="col-md-6 mb-4">
        <div class="card">
            <div class="card-header bg-primary text-white">
                <h5 class="card-title mb-0">Module Status</h5>
            </div>
            <div class="card-body">
                {% if diagnostics.module_status.error %}
                    <div class="alert alert-warning">{{ diagnostics.module_status.error }}</div>
                {% else %}
                    <table class="table table-sm">
                        <thead>
                            <tr>
                                <th>Module</th>
                                <th>Status</th>
                                <th>Error</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for module, status in diagnostics.module_status.items() %}
                            <tr>
                                <td>{{ module }}</td>
                                <td>
                                    {% if status.initialized %}
                                        <span class="badge bg-success">Initialized</span>
                                    {% else %}
                                        <span class="badge bg-danger">Failed</span>
                                    {% endif %}
                                </td>
                                <td>
                                    {% if status.error %}
                                        <span class="text-danger">{{ status.error }}</span>
                                    {% else %}
                                        <span class="text-muted">None</span>
                                    {% endif %}
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                {% endif %}
            </div>
        </div>
    </div>
    
    <!-- Template Information -->
    <div class="col-md-6 mb-4">
        <div class="card">
            <div class="card-header bg-primary text-white">
                <h5 class="card-title mb-0">Template Information</h5>
            </div>
            <div class="card-body">
                {% if diagnostics.template_info.error %}
                    <div class="alert alert-warning">{{ diagnostics.template_info.error }}</div>
                {% else %}
                    <table class="table table-sm">
                        <tr>
                            <th>Path:</th>
                            <td>{{ diagnostics.template_info.path }}</td>
                        </tr>
                        <tr>
                            <th>Directory Exists:</th>
                            <td>{{ diagnostics.template_info.exists }}</td>
                        </tr>
                        {% if diagnostics.template_info.base_exists %}
                        <tr>
                            <th>base.html:</th>
                            <td>Exists ({{ diagnostics.template_info.base_size }} bytes)</td>
                        </tr>
                        {% endif %}
                        {% if diagnostics.template_info.index_exists %}
                        <tr>
                            <th>index.html:</th>
                            <td>Exists ({{ diagnostics.template_info.index_size }} bytes)</td>
                        </tr>
                        {% endif %}
                    </table>
                    
                    {% if diagnostics.template_info.files %}
                    <h6 class="mt-3">Available Templates:</h6>
                    <ul class="list-group">
                        {% for template in diagnostics.template_info.files %}
                        <li class="list-group-item">{{ template }}</li>
                        {% endfor %}
                    </ul>
                    {% endif %}
                {% endif %}
            </div>
        </div>
    </div>
    
    <!-- Database Information -->
    <div class="col-md-6 mb-4">
        <div class="card">
            <div class="card-header bg-primary text-white">
                <h5 class="card-title mb-0">Database Information</h5>
            </div>
            <div class="card-body">
                {% if diagnostics.database_info.error %}
                    <div class="alert alert-danger">{{ diagnostics.database_info.error }}</div>
                {% else %}
                    <table class="table table-sm">
                        <tr>
                            <th>Path:</th>
                            <td>{{ diagnostics.database_info.path }}</td>
                        </tr>
                        <tr>
                            <th>Database Exists:</th>
                            <td>{% if diagnostics.database_info.exists %}<span class="text-success">Yes</span>{% else %}<span class="text-danger">No</span>{% endif %}</td>
                        </tr>
                        {% if diagnostics.database_info.exists %}
                            <tr>
                                <th>Users Table:</th>
                                <td>{% if diagnostics.database_info.users_table_exists %}<span class="text-success">Yes</span>{% else %}<span class="text-danger">No</span>{% endif %}</td>
                            </tr>
                            {% if diagnostics.database_info.users_table_exists %}
                                <tr>
                                    <th>User Count:</th>
                                    <td>{{ diagnostics.database_info.user_count }}</td>
                                </tr>
                                <tr>
                                    <th>Admin User:</th>
                                    <td>{% if diagnostics.database_info.admin_user_exists %}<span class="text-success">Yes</span>{% else %}<span class="text-danger">No</span>{% endif %}</td>
                                </tr>
                            {% endif %}
                        {% endif %}
                    </table>
                {% endif %}
            </div>
        </div>
    </div>
</div>
{% endblock %}

{% block scripts %}
<script>
    document.addEventListener('DOMContentLoaded', function() {
        // Recreate templates button
        const recreateBtn = document.getElementById('recreate-templates-btn');
        if (recreateBtn) {
            recreateBtn.addEventListener('click', function() {
                if (confirm('Are you sure you want to recreate all templates? This may overwrite existing templates.')) {
                    fetch('/recreate-templates', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'}
                    })
                    .then(response => response.json())
                    .then(data => {
                        alert(data.message);
                        location.reload();
                    })
                    .catch(error => {
                        console.error('Error:', error);
                        alert('An error occurred while recreating templates.');
                    });
                }
            });
        }
        
        // Initialize database button
        const initDbBtn = document.getElementById('init-database-btn');
        if (initDbBtn) {
            initDbBtn.addEventListener('click', function() {
                if (confirm('Are you sure you want to initialize the database? This may overwrite existing data.')) {
                    fetch('/init-database', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'}
                    })
                    .then(response => response.json())
                    .then(data => {
                        alert(data.message);
                        location.reload();
                    })
                    .catch(error => {
                        console.error('Error:', error);
                        alert('An error occurred while initializing the database.');
                    });
                }
            });
        }
    });
</script>
{% endblock %}"""
    }
    
    try:
        # Create templates directory
        template_dir = os.path.join(current_app.root_path, 'templates')
        os.makedirs(template_dir, exist_ok=True)
        
        # Generate templates
        for template_name, template_content in templates_to_generate.items():
            template_path = os.path.join(template_dir, template_name)
            needs_create = False
            
            if not os.path.exists(template_path):
                needs_create = True
                logger.info(f"Template {template_name} doesn't exist, creating it")
            else:
                # Check if template is too small
                try:
                    with open(template_path, 'r') as f:
                        content = f.read()
                    if len(content) < 100:  # Too small to be a proper template
                        needs_create = True
                        logger.info(f"Template {template_name} is too small ({len(content)} bytes), recreating it")
                except Exception as e:
                    needs_create = True
                    logger.error(f"Error reading template {template_name}: {e}, will recreate it")
            
            if needs_create:
                with open(template_path, 'w') as f:
                    f.write(template_content)
                logger.info(f"Created/recreated template: {template_name}")
                
        logger.info("All templates generated successfully")
    except Exception as e:
        logger.error(f"Error generating templates: {e}")
        logger.error(traceback.format_exc())
