from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, g, jsonify, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import sqlite3, json, os, datetime, logging, traceback
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash

# Configure logging
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
        
        # Set up context processor for common template variables
        app.context_processor(inject_template_variables)
        
        # Generate necessary templates and static files
        with app.app_context():
            # Ensure database directory exists
            os.makedirs(os.path.dirname(app.config.get('DATABASE_PATH', '/app/data/malware_platform.db')), exist_ok=True)
            
            # Ensure the database has been initialized
            if not os.path.exists(app.config.get('DATABASE_PATH')):
                init_db(app)
            
            # Generate templates
            generate_base_templates()
            
            logger.info("Web interface module initialized successfully")
        
    except Exception as e:
        logger.error(f"Error in web interface module initialization: {e}")
        # Don't re-raise to allow app to start with limited functionality

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

def init_db(app):
    """Initialize the database with schema"""
    logger.info("Initializing database")
    try:
        conn = sqlite3.connect(app.config.get('DATABASE_PATH'))
        cursor = conn.cursor()
        
        # Create users table
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
        
        conn.commit()
        conn.close()
        logger.info("Database initialization complete")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        raise

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
        conn = sqlite3.connect(current_app.config.get('DATABASE_PATH'))
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
        # Verify templates exist and are valid
        template_dir = current_app.template_folder
        if not os.path.isabs(template_dir):
            template_dir = os.path.join(current_app.root_path, template_dir)
            
        # Check if needed templates exist
        base_exists = os.path.exists(os.path.join(template_dir, 'base.html'))
        index_exists = os.path.exists(os.path.join(template_dir, 'index.html'))
        
        logger.info(f"Template check: base.html exists: {base_exists}, index.html exists: {index_exists}")
        
        # Try to create templates if they don't exist
        if not (base_exists and index_exists):
            logger.warning("Templates missing, generating them")
            generate_base_templates()
        
        # Render the template
        logger.info("Rendering index.html template")
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
                .links a {{ display: inline-block; margin: 0 10px; color: #4a6fa5; text-decoration: none; }}
                .links a:hover {{ text-decoration: underline; }}
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
            
            conn = _db_connection()
            cursor = conn.cursor()
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

@web_bp.route('/users/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_user():
    """Add new user - admin only"""
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role', 'analyst')
        
        if not username or not password:
            flash('Username and password are required', 'danger')
            return redirect(url_for('web.add_user'))
        
        try:
            # Check if username already exists
            conn = _db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
            if cursor.fetchone():
                conn.close()
                flash('Username already exists', 'danger')
                return redirect(url_for('web.add_user'))
            
            # Create new user
            cursor.execute(
                "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                (username, generate_password_hash(password), role)
            )
            conn.commit()
            conn.close()
            flash('User created successfully', 'success')
            return redirect(url_for('web.users'))
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            flash(f'Error creating user', 'danger')
    
    try:
        return render_template('user_form.html', user=None)
    except Exception as e:
        logger.error(f"Error rendering user form template: {e}")
        return redirect(url_for('web.users'))

@web_bp.route('/infrastructure')
@login_required
@admin_required
def infrastructure():
    """Infrastructure management page"""
    try:
        # Get GCP project info
        project_id = current_app.config.get('GCP_PROJECT_ID', 'Not configured')
        region = current_app.config.get('GCP_REGION', 'us-central1')
        
        # Get storage bucket info
        samples_bucket = current_app.config.get('GCP_STORAGE_BUCKET', 'Not configured')
        results_bucket = current_app.config.get('GCP_RESULTS_BUCKET', 'Not configured')
        
        # Get VM configuration
        vm_network = current_app.config.get('VM_NETWORK', 'detonation-network')
        vm_subnet = current_app.config.get('VM_SUBNET', 'detonation-subnet')
        vm_machine_type = current_app.config.get('VM_MACHINE_TYPE', 'e2-medium')
        
        return render_template('infrastructure.html', 
                             project_id=project_id,
                             region=region,
                             samples_bucket=samples_bucket,
                             results_bucket=results_bucket,
                             vm_network=vm_network,
                             vm_subnet=vm_subnet,
                             vm_machine_type=vm_machine_type)
    except Exception as e:
        logger.error(f"Error loading infrastructure data: {e}")
        flash("Error loading infrastructure data", "danger")
        return redirect(url_for('web.dashboard'))

@web_bp.route('/health')
def health_check():
    """Health check endpoint"""
    logger.info("Health check endpoint called on web blueprint")
    return jsonify({"status": "healthy", "source": "web_blueprint"}), 200

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
        return jsonify({"success": True, "message": "Templates recreated successfully"})
    except Exception as e:
        logger.error(f"Error recreating templates: {e}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500

@web_bp.route('/init-database', methods=['POST'])
@login_required
@admin_required
def initialize_database():
    """Initialize database endpoint"""
    try:
        init_db(current_app)
        return jsonify({"success": True, "message": "Database initialized successfully"})
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500

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
{% endblock %}"""
    }
    
    static_files = {
        'css/main.css': """/* Main CSS styles */
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
""",
        
        'js/main.js': """// Main JavaScript
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
    
    // Health check
    setInterval(function() {
        fetch('/health')
            .then(response => response.json())
            .then(data => {
                if (data.status !== 'healthy') {
                    console.warn('Health check reports unhealthy status:', data);
                }
            })
            .catch(error => console.error('Health check error:', error));
    }, 30000);
});
"""
    }
    
    try:
        # Create templates directory
        os.makedirs('templates', exist_ok=True)
        
        # Generate templates if they don't exist or are too small
        for template_name, template_content in templates_to_generate.items():
            template_path = f'templates/{template_name}'
            needs_create = False
            
            if not os.path.exists(template_path):
                needs_create = True
            else:
                # Check if template is too small
                try:
                    with open(template_path, 'r') as f:
                        content = f.read()
                    if len(content) < 100:  # Too small to be a proper template
                        needs_create = True
                except Exception:
                    needs_create = True
            
            if needs_create:
                with open(template_path, 'w') as f:
                    f.write(template_content)
                logger.info(f"Created/recreated template: {template_name}")
        
        # Create static files directories
        os.makedirs('static/css', exist_ok=True)
        os.makedirs('static/js', exist_ok=True)
        
        # Generate static files if they don't exist
        for filepath, content in static_files.items():
            full_path = f'static/{filepath}'
            if not os.path.exists(full_path):
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, 'w') as f:
                    f.write(content)
                logger.info(f"Created static file: {filepath}")
                
        logger.info("All templates and static files generated successfully")
    except Exception as e:
        logger.error(f"Error generating templates: {e}")
