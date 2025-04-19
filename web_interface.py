from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import os
import sqlite3
import json
import datetime
import logging
import traceback
import hashlib
import secrets
import subprocess
import time
import threading
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash
from pathlib import Path

# Configure logging
logger = logging.getLogger(__name__)

# Create blueprint - Root path is handled by this blueprint
web_bp = Blueprint('web', __name__)
login_manager = LoginManager()

class User(UserMixin):
    """User class for Flask-Login"""
    def __init__(self, id, username, role):
        self.id = id
        self.username = username
        self.role = role

class InfrastructureManager:
    """Class for managing cloud infrastructure using Terraform."""
    
    def __init__(self, app=None):
        """Initialize the infrastructure manager."""
        self.app = app
        self.terraform_dir = os.path.join(os.getcwd(), 'terraform')
        self.project_id = None
        self.region = 'us-central1'
        self.zone = 'us-central1-a'
        self.status = {
            "initialized": False,
            "last_apply": None,
            "error": None,
            "resources": {}
        }
        
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """Configure with Flask app settings."""
        self.app = app
        with app.app_context():
            self.project_id = app.config.get('GCP_PROJECT_ID')
            self.region = app.config.get('GCP_REGION', 'us-central1')
            self.zone = app.config.get('GCP_ZONE', 'us-central1-a')
            
            # Store in app context for global access
            app.infrastructure_manager = self
    
    def check_terraform_installed(self):
        """Check if Terraform is installed and available."""
        try:
            result = subprocess.run(['terraform', '--version'], 
                                   capture_output=True, text=True, check=True)
            logger.info(f"Terraform is installed: {result.stdout.splitlines()[0]}")
            return True
        except (subprocess.SubprocessError, FileNotFoundError):
            logger.warning("Terraform is not installed or not in PATH")
            return False
    
    def initialize(self):
        """Initialize Terraform configuration."""
        if not self.check_terraform_installed():
            self.status["error"] = "Terraform not installed"
            return False
            
        if not self.project_id:
            self.status["error"] = "No GCP Project ID configured"
            return False
            
        try:
            # Run terraform init
            result = subprocess.run(
                ['terraform', 'init'],
                cwd=self.terraform_dir,
                capture_output=True,
                text=True,
                check=True
            )
            
            logger.info(f"Terraform initialization successful")
            self.status["initialized"] = True
            self.status["error"] = None
            return True
        except subprocess.SubprocessError as e:
            error_msg = f"Terraform initialization failed: {str(e)}"
            logger.error(error_msg)
            self.status["error"] = error_msg
            return False
        except Exception as e:
            error_msg = f"Error during Terraform initialization: {str(e)}"
            logger.error(error_msg)
            self.status["error"] = error_msg
            return False
    
    def apply(self, auto_approve=False):
        """Apply Terraform configuration to create/update infrastructure."""
        if not self.status["initialized"]:
            if not self.initialize():
                return False
        
        try:
            # Build command with variables
            cmd = ['terraform', 'apply']
            
            # Add auto-approve if specified
            if auto_approve:
                cmd.append('-auto-approve')
                
            # Add variables
            cmd.extend([
                f'-var=project_id={self.project_id}',
                f'-var=region={self.region}',
                f'-var=zone={self.zone}'
            ])
            
            # Run terraform apply
            logger.info(f"Running terraform apply")
            result = subprocess.run(
                cmd,
                cwd=self.terraform_dir,
                capture_output=True,
                text=True,
                check=True
            )
            
            logger.info("Terraform apply successful")
            self.status["last_apply"] = time.time()
            self.status["error"] = None
            
            # Update resource information
            self._update_resource_info()
            
            return True
        except subprocess.SubprocessError as e:
            error_msg = f"Terraform apply failed: {str(e)}"
            logger.error(error_msg)
            self.status["error"] = error_msg
            return False
        except Exception as e:
            error_msg = f"Error during Terraform apply: {str(e)}"
            logger.error(error_msg)
            self.status["error"] = error_msg
            return False
    
    def destroy(self, auto_approve=False):
        """Destroy infrastructure created by Terraform."""
        if not self.status["initialized"]:
            if not self.initialize():
                return False
                
        try:
            # Build command
            cmd = ['terraform', 'destroy']
            
            # Add auto-approve if specified
            if auto_approve:
                cmd.append('-auto-approve')
                
            # Add variables
            cmd.extend([
                f'-var=project_id={self.project_id}',
                f'-var=region={self.region}',
                f'-var=zone={self.zone}'
            ])
            
            # Run terraform destroy
            logger.info(f"Running terraform destroy")
            result = subprocess.run(
                cmd,
                cwd=self.terraform_dir,
                capture_output=True,
                text=True,
                check=True
            )
            
            logger.info("Terraform destroy successful")
            self.status["resources"] = {}
            return True
        except subprocess.SubprocessError as e:
            error_msg = f"Terraform destroy failed: {str(e)}"
            logger.error(error_msg)
            self.status["error"] = error_msg
            return False
        except Exception as e:
            error_msg = f"Error during Terraform destroy: {str(e)}"
            logger.error(error_msg)
            self.status["error"] = error_msg
            return False
    
    def get_outputs(self):
        """Get Terraform outputs."""
        if not self.status["initialized"]:
            if not self.initialize():
                return {}
                
        try:
            # Run terraform output
            result = subprocess.run(
                ['terraform', 'output', '-json'],
                cwd=self.terraform_dir,
                capture_output=True,
                text=True,
                check=True
            )
            
            # Parse JSON output
            outputs = json.loads(result.stdout)
            
            # Extract values from the output structure
            return {k: v.get('value') for k, v in outputs.items()}
        except Exception as e:
            logger.error(f"Error getting Terraform outputs: {str(e)}")
            return {}
    
    def _update_resource_info(self):
        """Update information about deployed resources."""
        try:
            # Get outputs which include resource information
            outputs = self.get_outputs()
            
            # Extract resource information
            self.status["resources"] = {
                "storage": {
                    "malware_samples_bucket": outputs.get("malware_samples_bucket"),
                    "detonation_results_bucket": outputs.get("detonation_results_bucket")
                },
                "pubsub": {
                    "topic": outputs.get("pubsub_topic")
                },
                "vm_templates": {
                    "windows": outputs.get("windows_template"),
                    "linux": outputs.get("linux_template")
                },
                "service": {
                    "url": outputs.get("service_url")
                }
            }
        except Exception as e:
            logger.error(f"Error updating resource information: {str(e)}")
            self.status["resources"] = {}
    
    def apply_async(self, auto_approve=True, callback=None):
        """Apply Terraform configuration asynchronously."""
        def _async_apply():
            success = self.apply(auto_approve)
            if callback:
                callback(success)
        
        thread = threading.Thread(target=_async_apply)
        thread.daemon = True
        thread.start()
        return thread

def generate_admin_password(app):
    """Generate a deterministic admin password based on app configuration."""
    try:
        # Create a seed string using app configuration
        seed = f"{app.config.get('SECRET_KEY', '')}:{app.config.get('GCP_PROJECT_ID', '')}:{os.environ.get('HOSTNAME', '')}:admin_password_seed"
        password_hash = hashlib.sha256(seed.encode()).hexdigest()
        # Create a complex password: first 12 chars of hash + complexity chars
        return password_hash[:12] + 'A1$z'
    except Exception as e:
        logger.error(f"Error generating admin password: {e}")
        return f"Secure{secrets.token_hex(8)}!"

def init_app(app):
    """Initialize web interface module with Flask app"""
    try:
        # Register blueprint first
        app.register_blueprint(web_bp)
        logger.info("Web interface blueprint registered successfully")
        
        # Set up exception handling
        app.errorhandler(500)(handle_server_error)
        app.errorhandler(Exception)(handle_exception)
        
        # Setup login manager
        login_manager.init_app(app)
        login_manager.login_view = 'web.login'
        login_manager.login_message = "Please log in to access this page."
        login_manager.login_message_category = "info"
        
        # Set up context processor for template variables
        app.context_processor(inject_template_variables)
        
        # Generate application essentials
        with app.app_context():
            # These operations must be in the correct order
            ensure_directories(app)
            ensure_db_tables(app)
            generate_base_templates(app)
            generate_static_files(app)
        
        # Initialize infrastructure manager
        try:
            if app.config.get('INITIALIZE_GCP', False):
                infra_manager = InfrastructureManager()
                infra_manager.init_app(app)
                # Optionally initialize Terraform, but don't apply
                if infra_manager.initialize():
                    logger.info("Infrastructure manager initialized successfully")
                else:
                    logger.warning("Infrastructure initialization failed, but continuing")
        except Exception as e:
            logger.error(f"Error initializing infrastructure manager: {e}")
            
        logger.info("Web interface module initialized successfully")
    except Exception as e:
        logger.error(f"Error in web interface initialization: {e}\n{traceback.format_exc()}")
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
            logger.debug(f"Ensured directory exists: {directory}")
        except Exception as e:
            logger.error(f"Error creating directory {directory}: {e}")

def handle_server_error(e):
    """Handle 500 errors gracefully"""
    error_traceback = traceback.format_exc()
    logger.error(f"Server error: {str(e)}\n{error_traceback}")
    debug_mode = current_app.config.get('DEBUG', False)
    
    return render_template('error.html', 
                          error_code=500,
                          error_message=f"Server error: {str(e)}" if debug_mode else "The server encountered an internal error.",
                          error_details=error_traceback if debug_mode else None), 500

def handle_exception(e):
    """Handle uncaught exceptions"""
    error_traceback = traceback.format_exc()
    logger.error(f"Uncaught exception: {str(e)}\n{error_traceback}")
    debug_mode = current_app.config.get('DEBUG', False)
    
    return render_template('error.html', 
                          error_code=500,
                          error_message=f"Uncaught exception: {str(e)}" if debug_mode else "The server encountered an internal error.",
                          error_details=error_traceback if debug_mode else None), 500

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

def _db_connection(row_factory=None):
    """Create a database connection with optional row factory"""
    try:
        db_path = current_app.config.get('DATABASE_PATH')
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        conn = sqlite3.connect(db_path)
        if row_factory:
            conn.row_factory = row_factory
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        raise

def ensure_db_tables(app):
    """Ensure database tables exist and admin user is created"""
    try:
        # Get database path
        db_path = app.config.get('DATABASE_PATH')
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        # Connect and check for users table
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        table_exists = cursor.fetchone() is not None
        
        # Generate admin password
        admin_password = generate_admin_password(app)
        
        if not table_exists:
            logger.info("Users table doesn't exist, creating it")
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )''')
            
            # Create admin user
            cursor.execute(
                "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                ("admin", generate_password_hash(admin_password), "admin")
            )
            logger.info(f"Created admin user with password: {admin_password}")
        else:
            # Check if admin user exists
            cursor.execute("SELECT COUNT(*) FROM users WHERE username = 'admin'")
            if cursor.fetchone()[0] == 0:
                cursor.execute(
                    "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                    ("admin", generate_password_hash(admin_password), "admin")
                )
                logger.info(f"Created admin user with password: {admin_password}")
        
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
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
            admin_password = generate_admin_password(current_app)
            
            cursor.execute(
                "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                ("admin", generate_password_hash(admin_password), "admin")
            )
            logger.info(f"Created admin user with password: {admin_password}")
        
        # Create infrastructure status table for tracking
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS infrastructure_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            component TEXT NOT NULL,
            status TEXT NOT NULL,
            details TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        
        logger.info("Web interface database schema created successfully")
    except Exception as e:
        logger.error(f"Error creating web interface database schema: {e}")
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

# Routes
@web_bp.route('/')
def index():
    """Home page"""
    try:
        return render_template('index.html')
    except Exception as e:
        logger.error(f"Error rendering index page: {str(e)}\n{traceback.format_exc()}")
        
        # Fallback to a minimal response if template rendering fails
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Malware Detonation Platform</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; }}
                h1 {{ color: #4a6fa5; }}
                .links {{ margin-top: 20px; }}
                .links a {{ display: inline-block; margin: 10px; padding: 10px; background-color: #4a6fa5; color: white; text-decoration: none; border-radius: 4px; }}
            </style>
        </head>
        <body>
            <h1>Malware Detonation Platform</h1>
            <p>Welcome to the platform.</p>
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
            
            # Ensure database exists
            db_path = current_app.config.get('DATABASE_PATH')
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
                
            if not os.path.exists(db_path):
                ensure_db_tables(current_app)
            
            conn = _db_connection()
            cursor = conn.cursor()
            
            # Check if users table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
            if cursor.fetchone() is None:
                create_database_schema(cursor)
                conn.commit()
            
            cursor.execute("SELECT id, username, password, role FROM users WHERE username = ?", (username,))
            user_data = cursor.fetchone()
            conn.close()
            
            if user_data and check_password_hash(user_data[2], password):
                user = User(user_data[0], user_data[1], user_data[3])
                login_user(user, remember=remember)
                
                next_page = request.args.get('next')
                if not next_page or not next_page.startswith('/'):
                    next_page = url_for('web.dashboard')
                return redirect(next_page)
                
            error = 'Invalid username or password'
        except Exception as e:
            logger.error(f"Login error: {e}")
            error = 'An error occurred during login. Please try again.'
    
    try:
        return render_template('login.html', error=error)
    except Exception as e:
        logger.error(f"Error rendering login template: {e}")
        # Fallback to a basic login form
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
                <p><small>Default username: admin</small></p>
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
    # Get recent data safely
    datasets = []
    analyses = []
    visualizations = []
    
    try:
        from main import get_module
        
        # Try to get malware samples
        malware_module = get_module('malware')
        if malware_module:
            if hasattr(malware_module, 'get_datasets'):
                datasets = malware_module.get_datasets()
            elif hasattr(malware_module, 'get_recent_samples'):
                datasets = malware_module.get_recent_samples(5)
        
        # Try to get detonation jobs
        detonation_module = get_module('detonation')
        if detonation_module and hasattr(detonation_module, 'get_detonation_jobs'):
            analyses = detonation_module.get_detonation_jobs()[:5] if hasattr(detonation_module.get_detonation_jobs(), '__len__') else []
        
        # Try to get visualizations
        viz_module = get_module('viz')
        if viz_module and hasattr(viz_module, 'get_visualizations_for_dashboard'):
            visualizations = viz_module.get_visualizations_for_dashboard()
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
        # Try using MODULES directly from main
        try:
            from main import MODULES
            diagnostics['module_status'] = {name: {
                "initialized": info.get("initialized", False),
                "error": info.get("error", None)
            } for name, info in MODULES.items()}
        except ImportError:
            diagnostics['module_status'] = {'error': 'Could not import module status from main'}
    
    # Check template files
    try:
        template_dir = current_app.template_folder
        diagnostics['template_info']['path'] = template_dir
        diagnostics['template_info']['exists'] = os.path.exists(template_dir)
        
        if diagnostics['template_info']['exists']:
            templates = os.listdir(template_dir)
            diagnostics['template_info']['files'] = templates
            diagnostics['template_info']['base_exists'] = 'base.html' in templates
            diagnostics['template_info']['index_exists'] = 'index.html' in templates
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
    
    try:
        return render_template('diagnostic.html', diagnostics=diagnostics)
    except Exception as e:
        logger.error(f"Error rendering diagnostic template: {e}")
        # Return JSON response if template fails
        return jsonify(diagnostics)

@web_bp.route('/health')
def health_check():
    """Health check endpoint"""
    health_data = {"status": "healthy", "source": "web_blueprint"}
    
    # Check database health
    try:
        conn = _db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        health_data["database"] = {"status": "healthy", "user_count": cursor.fetchone()[0]}
        conn.close()
    except Exception as e:
        health_data["database"] = {"status": "unhealthy", "error": str(e)}
        health_data["status"] = "degraded"
    
    # Check template directory
    try:
        template_dir = current_app.template_folder
        health_data["templates"] = {
            "status": "healthy" if os.path.exists(template_dir) else "unhealthy",
            "path": template_dir
        }
        if not os.path.exists(template_dir):
            health_data["status"] = "degraded"
    except Exception as e:
        health_data["templates"] = {"status": "unhealthy", "error": str(e)}
        health_data["status"] = "degraded"
    
    health_data["timestamp"] = datetime.datetime.now().isoformat()
    return jsonify(health_data)

@web_bp.route('/recreate-templates', methods=['POST'])
def recreate_templates():
    """Recreate basic templates endpoint"""
    try:
        generate_base_templates(current_app)
        generate_static_files(current_app)
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

@web_bp.route('/infrastructure')
@login_required
@admin_required
def infrastructure():
    """Infrastructure management page"""
    try:
        # Get infrastructure manager
        infra_manager = current_app.infrastructure_manager if hasattr(current_app, 'infrastructure_manager') else None
        
        # Get infrastructure status
        if infra_manager:
            tf_installed = infra_manager.check_terraform_installed()
            outputs = infra_manager.get_outputs() if infra_manager.status["initialized"] else {}
            status = infra_manager.status
        else:
            tf_installed = False
            outputs = {}
            status = {"initialized": False, "error": "Infrastructure manager not initialized"}
            
        return render_template('infrastructure.html', 
                              tf_installed=tf_installed,
                              status=status,
                              outputs=outputs)
    except Exception as e:
        logger.error(f"Error in infrastructure page: {e}")
        flash(f"Error loading infrastructure management: {str(e)}", "error")
        return redirect(url_for('web.dashboard'))

@web_bp.route('/infrastructure/apply', methods=['POST'])
@login_required
@admin_required
def infrastructure_apply():
    """Apply Terraform configuration"""
    try:
        # Get infrastructure manager
        infra_manager = current_app.infrastructure_manager if hasattr(current_app, 'infrastructure_manager') else None
        
        if not infra_manager:
            flash("Infrastructure manager not initialized", "error")
            return redirect(url_for('web.infrastructure'))
        
        # Apply asynchronously to avoid blocking the request
        def apply_callback(success):
            if success:
                # Can't use flash here as we're in a background thread
                logger.info("Terraform apply completed successfully")
            else:
                logger.error(f"Terraform apply failed: {infra_manager.status['error']}")
        
        infra_manager.apply_async(auto_approve=True, callback=apply_callback)
        
        flash("Infrastructure deployment started. This may take several minutes.", "info")
        return redirect(url_for('web.infrastructure'))
    except Exception as e:
        logger.error(f"Error applying infrastructure: {e}")
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for('web.infrastructure'))

@web_bp.route('/infrastructure/destroy', methods=['POST'])
@login_required
@admin_required
def infrastructure_destroy():
    """Destroy infrastructure"""
    try:
        # Get infrastructure manager
        infra_manager = current_app.infrastructure_manager if hasattr(current_app, 'infrastructure_manager') else None
        
        if not infra_manager:
            flash("Infrastructure manager not initialized", "error")
            return redirect(url_for('web.infrastructure'))
        
        # Get confirmation from form
        confirm = request.form.get('confirm', '').lower() == 'destroy'
        
        if not confirm:
            flash("You must type 'destroy' to confirm infrastructure destruction", "warning")
            return redirect(url_for('web.infrastructure'))
        
        # Apply asynchronously to avoid blocking the request
        def destroy_callback(success):
            if success:
                logger.info("Terraform destroy completed successfully")
            else:
                logger.error(f"Terraform destroy failed: {infra_manager.status['error']}")
        
        infra_manager.apply_async(auto_approve=True, callback=destroy_callback)
        
        flash("Infrastructure destruction started. This may take several minutes.", "info")
        return redirect(url_for('web.infrastructure'))
    except Exception as e:
        logger.error(f"Error destroying infrastructure: {e}")
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for('web.infrastructure'))

@web_bp.route('/infrastructure/status')
@login_required
@admin_required
def infrastructure_status():
    """Get infrastructure status as JSON for AJAX requests"""
    try:
        # Get infrastructure manager
        infra_manager = current_app.infrastructure_manager if hasattr(current_app, 'infrastructure_manager') else None
        
        if not infra_manager:
            return jsonify({
                "initialized": False,
                "error": "Infrastructure manager not initialized"
            })
        
        # Get latest outputs
        outputs = infra_manager.get_outputs() if infra_manager.status["initialized"] else {}
        
        # Combine status and outputs
        status_data = {
            "initialized": infra_manager.status["initialized"],
            "last_apply": infra_manager.status["last_apply"],
            "error": infra_manager.status["error"],
            "resources": infra_manager.status["resources"],
            "outputs": outputs
        }
        
        return jsonify(status_data)
    except Exception as e:
        logger.error(f"Error getting infrastructure status: {e}")
        return jsonify({"error": str(e)}), 500

@web_bp.route('/add_user', methods=['GET', 'POST'])
@login_required
@admin_required
def add_user():
    """Add new user page and handler"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role', 'user')
        
        try:
            # Check if username already exists
            conn = _db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users WHERE username = ?", (username,))
            if cursor.fetchone()[0] > 0:
                flash(f"User '{username}' already exists", "danger")
                return redirect(url_for('web.add_user'))
                
            # Create new user
            cursor.execute(
                "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                (username, generate_password_hash(password), role)
            )
            conn.commit()
            conn.close()
            
            flash(f"User '{username}' created successfully", "success")
            return redirect(url_for('web.users'))
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            flash(f"Error creating user: {str(e)}", "danger")
            return redirect(url_for('web.add_user'))
    
    # GET request - show form
    roles = ['user', 'admin', 'analyst']
    return render_template('add_user.html', roles=roles)

def generate_static_files(app):
    """Generate CSS and JS files if they don't exist"""
    try:
        # Create directories
        css_dir = os.path.join(app.static_folder, 'css')
        js_dir = os.path.join(app.static_folder, 'js')
        os.makedirs(css_dir, exist_ok=True)
        os.makedirs(js_dir, exist_ok=True)
        
        # CSS file
        css_path = os.path.join(css_dir, 'main.css')
        if not os.path.exists(css_path):
            with open(css_path, 'w') as f:
                f.write("""/* Main CSS styles */
body { font-family: 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #333; background-color: #f8f9fa; }
.card { box-shadow: 0 2px 4px rgba(0,0,0,0.05); margin-bottom: 20px; border: none; border-radius: 8px; }
.card-header { border-top-left-radius: 8px !important; border-top-right-radius: 8px !important; }
.hash-value { font-family: monospace; word-break: break-all; }
.table-responsive { overflow-x: auto; }
footer { margin-top: 50px; padding: 20px 0; border-top: 1px solid #e9ecef; }
pre { background-color: #f8f9fa; padding: 10px; border-radius: 4px; border: 1px solid #dee2e6; white-space: pre-wrap; max-height: 300px; overflow-y: auto; }
""")
                logger.info("Created main CSS file")
        
        # JS file
        js_path = os.path.join(js_dir, 'main.js')
        if not os.path.exists(js_path):
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
        logger.error(f"Error generating static files: {e}")

def generate_base_templates(app=None):
    """Generate essential HTML templates for the application"""
    try:
        # Use current_app if app is not provided
        if app is None:
            app = current_app
            
        # Create templates directory
        template_dir = app.template_folder
        if not os.path.isabs(template_dir):
            template_dir = os.path.join(app.root_path, template_dir)
            
        os.makedirs(template_dir, exist_ok=True)
        
        # Define templates with infrastructure template included
        templates = {
            'base.html': """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}{{ app_name }}{% endblock %}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    <link href="{{ url_for('static', filename='css/main.css') }}" rel="stylesheet">
    {% block head %}{% endblock %}
    <style>
        .navbar { background-color: {{ colors.primary }} !important; }
        .btn-primary { background-color: {{ colors.primary }}; border-color: {{ colors.primary }}; }
        .btn-primary:hover { background-color: {{ colors.primary }}; filter: brightness(90%); }
    </style>
</head>
<body>
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

    <footer class="mt-5 py-3 text-center text-muted">
        <div class="container">
            <p>&copy; {{ year }} {{ app_name }}</p>
        </div>
    </footer>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
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
                    <small class="text-muted">Default username: admin (password available in system logs)</small>
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

            'dashboard.html': """{% extends 'base.html' %}
{% block title %}Dashboard - {{ app_name }}{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4">
    <h1>Dashboard</h1>
    <div class="btn-group">
        <a href="{{ url_for('malware.upload') }}" class="btn btn-primary">
            <i class="fas fa-upload"></i> Upload Sample
        </a>
        <a href="{{ url_for('viz.create') }}" class="btn btn-outline-primary">
            <i class="fas fa-chart-line"></i> Create Visualization
        </a>
    </div>
</div>

<!-- System Status -->
<div class="row mb-4">
    <div class="col-md-12">
        <div class="card">
            <div class="card-header bg-primary text-white">
                <h5 class="card-title mb-0">System Status</h5>
            </div>
            <div class="card-body">
                <div class="d-flex justify-content-between">
                    <div>
                        <span class="badge bg-success rounded-circle" style="width: 12px; height: 12px; display: inline-block;"></span>
                        Database: Connected
                    </div>
                    <div>
                        <span class="badge bg-success rounded-circle" style="width: 12px; height: 12px; display: inline-block;"></span>
                        Storage: Available
                    </div>
                    <div>
                        <span class="badge bg-success rounded-circle" style="width: 12px; height: 12px; display: inline-block;"></span>
                        VM Pool: Ready
                    </div>
                    <div>
                        <span class="badge bg-success rounded-circle" style="width: 12px; height: 12px; display: inline-block;"></span>
                        Analysis Engine: Running
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<!-- Stats Overview -->
<div class="row mb-4">
    <div class="col-md-3">
        <div class="card text-center">
            <div class="card-body">
                <h2 class="display-4">{{ datasets|length }}</h2>
                <p class="text-muted">Malware Samples</p>
            </div>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card text-center">
            <div class="card-body">
                <h2 class="display-4">{{ analyses|length }}</h2>
                <p class="text-muted">Detonation Jobs</p>
            </div>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card text-center">
            <div class="card-body">
                <h2 class="display-4">{{ visualizations|length }}</h2>
                <p class="text-muted">Visualizations</p>
            </div>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card text-center">
            <div class="card-body">
                <h2 class="display-4">{{ analyses|selectattr('status', 'equalto', 'running')|list|length }}</h2>
                <p class="text-muted">Running Jobs</p>
            </div>
        </div>
    </div>
</div>

<!-- Recent Activity and Resources -->
<div class="row">
    <!-- Recent Samples -->
    <div class="col-md-6">
        <div class="card">
            <div class="card-header bg-primary text-white">
                <h5 class="card-title mb-0">Recent Samples</h5>
            </div>
            <div class="card-body">
                {% if datasets %}
                    <div class="list-group">
                        {% for sample in datasets %}
                            <a href="{{ url_for('malware.view', sample_id=sample.id) }}" class="list-group-item list-group-item-action">
                                <div class="d-flex w-100 justify-content-between">
                                    <h6 class="mb-1">{{ sample.name }}</h6>
                                    <small>{{ sample.created_at|default('Unknown date', true) }}</small>
                                </div>
                                <p class="mb-1">Type: {{ sample.file_type }}</p>
                                <small class="text-muted">SHA256: {{ sample.sha256[:10] }}...</small>
                            </a>
                        {% endfor %}
                    </div>
                    <div class="text-center mt-3">
                        <a href="{{ url_for('malware.index') }}" class="btn btn-sm btn-outline-primary">View All Samples</a>
                    </div>
                {% else %}
                    <p class="text-muted">No samples available. <a href="{{ url_for('malware.upload') }}">Upload one now</a>.</p>
                {% endif %}
            </div>
        </div>
    </div>
    
    <!-- Recent Jobs -->
    <div class="col-md-6">
        <div class="card">
            <div class="card-header bg-primary text-white">
                <h5 class="card-title mb-0">Recent Detonation Jobs</h5>
            </div>
            <div class="card-body">
                {% if analyses %}
                    <div class="list-group">
                        {% for job in analyses %}
                            <a href="{{ url_for('detonation.view', job_id=job.id) }}" class="list-group-item list-group-item-action">
                                <div class="d-flex w-100 justify-content-between">
                                    <h6 class="mb-1">Job #{{ job.id }}</h6>
                                    <span class="badge {% if job.status == 'completed' %}bg-success{% elif job.status == 'failed' %}bg-danger{% elif job.status == 'running' %}bg-primary{% else %}bg-secondary{% endif %}">
                                        {{ job.status }}
                                    </span>
                                </div>
                                <p class="mb-1">Sample: {{ job.sample_name or "Unknown" }}</p>
                                <small class="text-muted">VM: {{ job.vm_type }}</small>
                            </a>
                        {% endfor %}
                    </div>
                    <div class="text-center mt-3">
                        <a href="{{ url_for('detonation.index') }}" class="btn btn-sm btn-outline-primary">View All Jobs</a>
                    </div>
                {% else %}
                    <p class="text-muted">No detonation jobs available.</p>
                {% endif %}
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

            'add_user.html': """{% extends 'base.html' %}
{% block title %}Add User - {{ app_name }}{% endblock %}
{% block content %}
<div class="row">
    <div class="col-md-6 mx-auto">
        <div class="card">
            <div class="card-header bg-primary text-white">
                <h2 class="card-title">Add New User</h2>
            </div>
            <div class="card-body">
                <form method="POST">
                    <div class="mb-3">
                        <label for="username" class="form-label">Username</label>
                        <input type="text" class="form-control" id="username" name="username" required>
                    </div>
                    
                    <div class="mb-3">
                        <label for="password" class="form-label">Password</label>
                        <input type="password" class="form-control" id="password" name="password" required>
                    </div>
                    
                    <div class="mb-3">
                        <label for="role" class="form-label">Role</label>
                        <select class="form-control" id="role" name="role">
                            {% for role in roles %}
                            <option value="{{ role }}">{{ role|title }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    
                    <div class="d-grid">
                        <button type="submit" class="btn btn-primary">Create User</button>
                    </div>
                </form>
                
                <div class="mt-3 text-center">
                    <a href="{{ url_for('web.users') }}" class="btn btn-outline-secondary">Cancel</a>
                </div>
            </div>
        </div>
    </div>
</div>
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
                            <td>Exists</td>
                        </tr>
                        {% endif %}
                        {% if diagnostics.template_info.index_exists %}
                        <tr>
                            <th>index.html:</th>
                            <td>Exists</td>
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
{% endblock %}""",

            'infrastructure.html': """{% extends 'base.html' %}

{% block title %}Infrastructure Management - {{ app_name }}{% endblock %}

{% block head %}
{{ super() }}
<style>
    .resource-card {
        margin-bottom: 20px;
    }
    .status-badge {
        font-size: 90%;
    }
    .terraform-output {
        background-color: #f8f9fa;
        padding: 15px;
        border-radius: 5px;
        font-family: monospace;
        margin: 15px 0;
        max-height: 300px;
        overflow-y: auto;
    }
    .refresh-btn {
        margin-left: 10px;
    }
    .destroy-confirmation {
        display: none;
        margin-top: 15px;
        padding: 15px;
        border: 1px solid #dc3545;
        border-radius: 5px;
        background-color: #f8d7da;
    }
</style>
{% endblock %}

{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4">
    <h1>Infrastructure Management</h1>
    <div>
        <button id="refresh-status" class="btn btn-outline-secondary">
            <i class="fas fa-sync"></i> Refresh Status
        </button>
        <a href="{{ url_for('web.dashboard') }}" class="btn btn-outline-secondary">
            <i class="fas fa-arrow-left"></i> Back to Dashboard
        </a>
    </div>
</div>

{% if not tf_installed %}
<div class="alert alert-warning">
    <i class="fas fa-exclamation-triangle"></i>
    <strong>Terraform Not Installed</strong>
    <p>Terraform is required for infrastructure management but is not installed on this server. Infrastructure operations will not be available.</p>
</div>
{% endif %}

<div class="row">
    <!-- Status and Controls -->
    <div class="col-md-4">
        <div class="card">
            <div class="card-header bg-primary text-white">
                <h5 class="card-title mb-0">Infrastructure Status</h5>
            </div>
            <div class="card-body">
                <p>
                    <strong>Terraform Initialized:</strong>
                    {% if status.initialized %}
                    <span class="badge bg-success">Yes</span>
                    {% else %}
                    <span class="badge bg-danger">No</span>
                    {% endif %}
                </p>
                
                {% if status.last_apply %}
                <p>
                    <strong>Last Applied:</strong>
                    <span id="last-apply-time">{{ status.last_apply|default('Never', true) }}</span>
                </p>
                {% endif %}
                
                {% if status.error %}
                <div class="alert alert-danger">
                    <strong>Error:</strong> {{ status.error }}
                </div>
                {% endif %}
                
                <div class="d-grid gap-2 mt-3">
                    <form method="POST" action="{{ url_for('web.infrastructure_apply') }}">
                        <button type="submit" class="btn btn-primary w-100" {% if not tf_installed %}disabled{% endif %}>
                            <i class="fas fa-play"></i> Apply Infrastructure
                        </button>
                    </form>
                    
                    <button id="destroy-btn" class="btn btn-danger w-100" {% if not tf_installed %}disabled{% endif %}>
                        <i class="fas fa-trash"></i> Destroy Infrastructure
                    </button>
                    
                    <div id="destroy-confirmation" class="destroy-confirmation">
                        <p class="fw-bold text-danger">Warning: This will destroy all infrastructure resources!</p>
                        <p>This action cannot be undone. Type "destroy" to confirm:</p>
                        <form method="POST" action="{{ url_for('web.infrastructure_destroy') }}" class="d-flex">
                            <input type="text" name="confirm" class="form-control me-2" placeholder="Type 'destroy'">
                            <button type="submit" class="btn btn-danger">Confirm</button>
                        </form>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <!-- Resources -->
    <div class="col-md-8">
        <div class="card mb-4">
            <div class="card-header bg-primary text-white">
                <h5 class="card-title mb-0">Infrastructure Resources</h5>
            </div>
            <div class="card-body">
                {% if status.resources %}
                
                <!-- Storage Resources -->
                <div class="resource-card">
                    <h5><i class="fas fa-database"></i> Storage Buckets</h5>
                    <table class="table table-sm">
                        <tr>
                            <th>Malware Samples Bucket:</th>
                            <td id="malware-bucket">{{ status.resources.storage.malware_samples_bucket|default('Not created', true) }}</td>
                        </tr>
                        <tr>
                            <th>Detonation Results Bucket:</th>
                            <td id="results-bucket">{{ status.resources.storage.detonation_results_bucket|default('Not created', true) }}</td>
                        </tr>
                    </table>
                </div>
                
                <!-- PubSub Resources -->
                <div class="resource-card">
                    <h5><i class="fas fa-comments"></i> PubSub Resources</h5>
                    <table class="table table-sm">
                        <tr>
                            <th>Detonation Topic:</th>
                            <td id="pubsub-topic">{{ status.resources.pubsub.topic|default('Not created', true) }}</td>
                        </tr>
                    </table>
                </div>
                
                <!-- VM Templates -->
                <div class="resource-card">
                    <h5><i class="fas fa-server"></i> VM Templates</h5>
                    <table class="table table-sm">
                        <tr>
                            <th>Windows Template:</th>
                            <td id="windows-template">{{ status.resources.vm_templates.windows|default('Not created', true) }}</td>
                        </tr>
                        <tr>
                            <th>Linux Template:</th>
                            <td id="linux-template">{{ status.resources.vm_templates.linux|default('Not created', true) }}</td>
                        </tr>
                    </table>
                </div>
                
                <!-- Service URL -->
                {% if status.resources.service and status.resources.service.url %}
                <div class="resource-card">
                    <h5><i class="fas fa-globe"></i> Service URL</h5>
                    <a href="{{ status.resources.service.url }}" target="_blank">{{ status.resources.service.url }}</a>
                </div>
                {% endif %}
                
                {% else %}
                <p class="text-muted">No infrastructure resources found. Use the "Apply Infrastructure" button to create resources.</p>
                {% endif %}
            </div>
        </div>
        
        <!-- Terraform Outputs -->
        <div class="card">
            <div class="card-header bg-primary text-white">
                <h5 class="card-title mb-0">Terraform Outputs</h5>
            </div>
            <div class="card-body">
                {% if outputs %}
                <pre class="terraform-output">{{ outputs|pprint }}</pre>
                {% else %}
                <p class="text-muted">No Terraform outputs available.</p>
                {% endif %}
            </div>
        </div>
    </div>
</div>
{% endblock %}

{% block scripts %}
<script>
    document.addEventListener('DOMContentLoaded', function() {
        // Handle destroy button
        const destroyBtn = document.getElementById('destroy-btn');
        const destroyConfirmation = document.getElementById('destroy-confirmation');
        
        if (destroyBtn) {
            destroyBtn.addEventListener('click', function() {
                destroyConfirmation.style.display = destroyConfirmation.style.display === 'none' ? 'block' : 'none';
            });
        }
        
        // Handle refresh button
        const refreshBtn = document.getElementById('refresh-status');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', function() {
                refreshInfrastructureStatus();
            });
        }
        
        // Format timestamps
        function formatTimestamp(timestamp) {
            if (!timestamp) return 'Never';
            const date = new Date(timestamp * 1000);
            return date.toLocaleString();
        }
        
        // Update last apply time
        const lastApplyTime = document.getElementById('last-apply-time');
        if (lastApplyTime && lastApplyTime.innerText !== 'Never') {
            lastApplyTime.innerText = formatTimestamp(parseFloat(lastApplyTime.innerText));
        }
        
        // Function to refresh infrastructure status
        function refreshInfrastructureStatus() {
            fetch('/infrastructure/status')
                .then(response => response.json())
                .then(data => {
                    // Update status fields
                    if (data.last_apply) {
                        document.getElementById('last-apply-time').innerText = formatTimestamp(data.last_apply);
                    }
                    
                    // Update resource fields if available
                    if (data.resources && data.resources.storage) {
                        document.getElementById('malware-bucket').innerText = 
                            data.resources.storage.malware_samples_bucket || 'Not created';
                        document.getElementById('results-bucket').innerText = 
                            data.resources.storage.detonation_results_bucket || 'Not created';
                    }
                    
                    if (data.resources && data.resources.pubsub) {
                        document.getElementById('pubsub-topic').innerText = 
                            data.resources.pubsub.topic || 'Not created';
                    }
                    
                    if (data.resources && data.resources.vm_templates) {
                        document.getElementById('windows-template').innerText = 
                            data.resources.vm_templates.windows || 'Not created';
                        document.getElementById('linux-template').innerText = 
                            data.resources.vm_templates.linux || 'Not created';
                    }
                    
                    // If there's a terraform output element, update it
                    const outputElement = document.querySelector('.terraform-output');
                    if (outputElement && data.outputs) {
                        outputElement.innerText = JSON.stringify(data.outputs, null, 2);
                    }
                })
                .catch(error => {
                    console.error('Error refreshing infrastructure status:', error);
                });
        }
        
        // Auto-refresh every 30 seconds if infrastructure changes are in progress
        const autoRefresh = setInterval(refreshInfrastructureStatus, 30000);
    });
</script>
{% endblock %}"""
        }
        
        # Create templates if they don't exist or are too small
        for name, content in templates.items():
            path = os.path.join(template_dir, name)
            if not os.path.exists(path) or os.path.getsize(path) < 100:
                with open(path, 'w') as f:
                    f.write(content)
                logger.info(f"Created/updated template: {name}")
    except Exception as e:
        logger.error(f"Error generating templates: {e}\n{traceback.format_exc()}")
        raise
