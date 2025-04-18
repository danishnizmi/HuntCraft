from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, g, jsonify, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import sqlite3, json, os, datetime, logging, traceback
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash

# Set up logger first
logger = logging.getLogger(__name__)

# Create blueprint immediately
web_bp = Blueprint('web', __name__, url_prefix='')
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
        app.errorhandler(404)(handle_not_found)
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

def handle_not_found(e):
    """Handle 404 errors gracefully"""
    return render_template('error.html',
                          error_code=404,
                          error_message="The requested page was not found."), 404

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

# Routes
@web_bp.route('/')
def index():
    """Home page"""
    try:
        # Check if templates exist
        template_dir = current_app.template_folder
        if not os.path.isabs(template_dir):
            template_dir = os.path.join(current_app.root_path, template_dir)
            
        base_exists = os.path.exists(os.path.join(template_dir, 'base.html'))
        index_exists = os.path.exists(os.path.join(template_dir, 'index.html'))
        
        logger.info(f"Template directory: {template_dir}, base.html exists: {base_exists}, index.html exists: {index_exists}")
        
        # Try to create templates if they don't exist
        if not (base_exists and index_exists):
            logger.warning("Templates missing, attempting to recreate them")
            from main import ensure_index_template
            ensure_index_template(current_app)
        
        # Render the template
        logger.info("Attempting to render index.html template")
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
            <p>The application is available but templates could not be loaded.</p>
            <div class="links">
                <a href="/malware">Malware Analysis</a>
                <a href="/detonation">Detonation Service</a>
                <a href="/viz">Visualizations</a>
                <a href="/health">Health Check</a>
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
    
    return render_template('login.html', error=error)

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
            else:
                logger.warning("Malware module or get_datasets function not available")
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
    
    return render_template('dashboard.html', 
                         datasets=datasets, 
                         analyses=analyses,
                         visualizations=visualizations)

@web_bp.route('/profile')
@login_required
def profile():
    """User profile page"""
    return render_template('profile.html')

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
    
    return render_template('users.html', users=users_list)

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
    
    return render_template('user_form.html', user=None)

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
    return jsonify({"status": "healthy"}), 200

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
        'database_info': {}
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
    
    return render_template('diagnostic.html', diagnostics=diagnostics)

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
                <h2 class="card-title text-center">Login</h2>
            </div>
            <div class="card-body">
                {% if error %}
                <div class="alert alert-danger">{{ error }}</div>
                {% endif %}
                
                <form method="POST">
                    <div class="mb-3">
                        <label for="username" class="form-label">Username</label>
                        <input type="text" class="form-control" id="username" name="username" required autofocus>
                    </div>
                    <div class="mb-3">
                        <label for="password" class="form-label">Password</label>
                        <input type="password" class="form-control" id="password" name="password" required>
                    </div>
                    <div class="mb-3 form-check">
                        <input type="checkbox" class="form-check-input" id="remember" name="remember">
                        <label class="form-check-label" for="remember">Remember me</label>
                    </div>
                    <div class="d-grid">
                        <button type="submit" class="btn btn-primary">Login</button>
                    </div>
                </form>
                
                <div class="text-center mt-3">
                    <p class="text-muted">Default credentials: <code>admin / admin123</code></p>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}""",
        
        'dashboard.html': """{% extends 'base.html' %}

{% block title %}Dashboard - {{ app_name }}{% endblock %}

{% block content %}
<h1 class="mb-4">Dashboard</h1>

<div class="row mb-4">
    <div class="col-md-6">
        <div class="card">
            <div class="card-header bg-primary text-white">
                <h5 class="card-title mb-0">Platform Status</h5>
            </div>
            <div class="card-body">
                <div class="row">
                    <div class="col-sm-6">
                        <div class="text-center p-3">
                            <i class="fas fa-virus fa-3x mb-2 text-primary"></i>
                            <h2 id="samples-count">{{ datasets|length }}</h2>
                            <p class="text-muted">Malware Samples</p>
                        </div>
                    </div>
                    <div class="col-sm-6">
                        <div class="text-center p-3">
                            <i class="fas fa-flask fa-3x mb-2 text-primary"></i>
                            <h2 id="detonations-count">{{ analyses|length }}</h2>
                            <p class="text-muted">Detonation Jobs</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <div class="col-md-6">
        <div class="card">
            <div class="card-header bg-primary text-white">
                <h5 class="card-title mb-0">Quick Actions</h5>
            </div>
            <div class="card-body">
                <div class="row text-center">
                    <div class="col-sm-4">
                        <a href="{{ url_for('malware.upload') }}" class="btn btn-outline-primary btn-sm d-block mb-2">
                            <i class="fas fa-upload"></i>
                        </a>
                        <small>Upload Sample</small>
                    </div>
                    <div class="col-sm-4">
                        <a href="{{ url_for('detonation.index') }}" class="btn btn-outline-primary btn-sm d-block mb-2">
                            <i class="fas fa-flask"></i>
                        </a>
                        <small>New Detonation</small>
                    </div>
                    <div class="col-sm-4">
                        <a href="{{ url_for('viz.create') }}" class="btn btn-outline-primary btn-sm d-block mb-2">
                            <i class="fas fa-chart-line"></i>
                        </a>
                        <small>New Visualization</small>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<div class="row">
    <div class="col-md-6">
        <div class="card">
            <div class="card-header bg-primary text-white">
                <h5 class="card-title mb-0">Recent Malware Samples</h5>
            </div>
            <div class="card-body">
                {% if datasets %}
                    <div class="list-group">
                    {% for dataset in datasets %}
                        <a href="{{ url_for('malware.view', sample_id=dataset.id) }}" class="list-group-item list-group-item-action">
                            <div class="d-flex w-100 justify-content-between">
                                <h6 class="mb-1">{{ dataset.name }}</h6>
                                <small>{{ dataset.created_at }}</small>
                            </div>
                            <small class="text-muted">SHA256: {{ dataset.sha256[:12] }}...</small>
                        </a>
                    {% endfor %}
                    </div>
                {% else %}
                    <p class="text-muted text-center">No recent samples.</p>
                {% endif %}
                
                <div class="text-center mt-3">
                    <a href="{{ url_for('malware.index') }}" class="btn btn-sm btn-outline-primary">View All Samples</a>
                </div>
            </div>
        </div>
    </div>
    
    <div class="col-md-6">
        <div class="card">
            <div class="card-header bg-primary text-white">
                <h5 class="card-title mb-0">Recent Detonation Jobs</h5>
            </div>
            <div class="card-body">
                {% if analyses %}
                    <div class="list-group">
                    {% for analysis in analyses %}
                        <a href="{{ url_for('detonation.view', job_id=analysis.id) }}" class="list-group-item list-group-item-action">
                            <div class="d-flex w-100 justify-content-between">
                                <h6 class="mb-1">Job #{{ analysis.id }}</h6>
                                <small class="badge {% if analysis.status == 'completed' %}bg-success{% elif analysis.status == 'failed' %}bg-danger{% else %}bg-warning{% endif %}">
                                    {{ analysis.status }}
                                </small>
                            </div>
                            <small class="text-muted">Sample: {{ analysis.sample_name }}</small>
                        </a>
                    {% endfor %}
                    </div>
                {% else %}
                    <p class="text-muted text-center">No recent detonation jobs.</p>
                {% endif %}
                
                <div class="text-center mt-3">
                    <a href="{{ url_for('detonation.index') }}" class="btn btn-sm btn-outline-primary">View All Jobs</a>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}""",

        'profile.html': """{% extends 'base.html' %}

{% block title %}User Profile - {{ app_name }}{% endblock %}

{% block content %}
<div class="row justify-content-center">
    <div class="col-md-8">
        <div class="card">
            <div class="card-header bg-primary text-white">
                <h2 class="card-title">User Profile</h2>
            </div>
            <div class="card-body">
                <div class="row mb-4">
                    <div class="col-md-3 text-center">
                        <i class="fas fa-user-circle fa-5x text-primary"></i>
                    </div>
                    <div class="col-md-9">
                        <h3>{{ current_user.username }}</h3>
                        <p><strong>Role:</strong> {{ current_user.role }}</p>
                        <p><strong>User ID:</strong> {{ current_user.id }}</p>
                    </div>
                </div>
                
                <h4>Change Password</h4>
                <hr>
                
                <form method="POST" action="{{ url_for('web.profile') }}">
                    <div class="mb-3">
                        <label for="current_password" class="form-label">Current Password</label>
                        <input type="password" class="form-control" id="current_password" name="current_password">
                    </div>
                    
                    <div class="mb-3">
                        <label for="new_password" class="form-label">New Password</label>
                        <input type="password" class="form-control" id="new_password" name="new_password">
                    </div>
                    
                    <div class="mb-3">
                        <label for="confirm_password" class="form-label">Confirm New Password</label>
                        <input type="password" class="form-control" id="confirm_password" name="confirm_password">
                    </div>
                    
                    <button type="submit" class="btn btn-primary">Update Password</button>
                </form>
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

        'infrastructure.html': """{% extends 'base.html' %}

{% block title %}Infrastructure - {{ app_name }}{% endblock %}

{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4">
    <h1>Infrastructure Management</h1>
    <div>
        <a href="{{ url_for('web.dashboard') }}" class="btn btn-outline-secondary">
            <i class="fas fa-arrow-left"></i> Back to Dashboard
        </a>
    </div>
</div>

<div class="row">
    <div class="col-md-6">
        <div class="card mb-4">
            <div class="card-header bg-primary text-white">
                <h5 class="card-title mb-0">GCP Configuration</h5>
            </div>
            <div class="card-body">
                <table class="table table-sm">
                    <tr>
                        <th width="35%">Project ID:</th>
                        <td>{{ project_id }}</td>
                    </tr>
                    <tr>
                        <th>Region:</th>
                        <td>{{ region }}</td>
                    </tr>
                    <tr>
                        <th>Samples Bucket:</th>
                        <td>{{ samples_bucket }}</td>
                    </tr>
                    <tr>
                        <th>Results Bucket:</th>
                        <td>{{ results_bucket }}</td>
                    </tr>
                </table>
                
                <div class="d-grid gap-2 mt-3">
                    <button class="btn btn-outline-primary" onclick="checkGCPResources()">
                        <i class="fas fa-check-circle"></i> Verify GCP Resources
                    </button>
                </div>
            </div>
        </div>
        
        <div class="card">
            <div class="card-header bg-primary text-white">
                <h5 class="card-title mb-0">System Health</h5>
            </div>
            <div class="card-body">
                <div class="d-flex justify-content-between mb-3">
                    <h6>Application Status:</h6>
                    <span class="badge bg-success"><i class="fas fa-check"></i> Running</span>
                </div>
                
                <div class="d-flex justify-content-between mb-3">
                    <h6>Database Status:</h6>
                    <span class="badge bg-success"><i class="fas fa-check"></i> Connected</span>
                </div>
                
                <div class="d-flex justify-content-between mb-3">
                    <h6>Storage Status:</h6>
                    <span class="badge bg-success"><i class="fas fa-check"></i> Available</span>
                </div>
                
                <div class="progress mt-3">
                    <div class="progress-bar bg-success" role="progressbar" style="width: 25%;" aria-valuenow="25" aria-valuemin="0" aria-valuemax="100">25% Disk Usage</div>
                </div>
            </div>
        </div>
    </div>
    
    <div class="col-md-6">
        <div class="card mb-4">
            <div class="card-header bg-primary text-white">
                <h5 class="card-title mb-0">Detonation VM Configuration</h5>
            </div>
            <div class="card-body">
                <table class="table table-sm">
                    <tr>
                        <th width="35%">Network:</th>
                        <td>{{ vm_network }}</td>
                    </tr>
                    <tr>
                        <th>Subnet:</th>
                        <td>{{ vm_subnet }}</td>
                    </tr>
                    <tr>
                        <th>Machine Type:</th>
                        <td>{{ vm_machine_type }}</td>
                    </tr>
                    <tr>
                        <th>Auto-deletion:</th>
                        <td><span class="badge bg-success">Enabled</span></td>
                    </tr>
                </table>
                
                <div class="alert alert-info mt-3">
                    <i class="fas fa-info-circle"></i> VM templates are configured with automatic cleanup after detonation completes.
                </div>
                
                <div class="d-grid gap-2 mt-3">
                    <button class="btn btn-outline-primary" onclick="testVMDeployment()">
                        <i class="fas fa-server"></i> Test VM Deployment
                    </button>
                </div>
            </div>
        </div>
        
        <div class="card">
            <div class="card-header bg-primary text-white">
                <h5 class="card-title mb-0">System Logs</h5>
            </div>
            <div class="card-body">
                <div class="mb-3">
                    <label for="log-level" class="form-label">Log Level</label>
                    <select class="form-select" id="log-level">
                        <option value="info">Info</option>
                        <option value="warning">Warning</option>
                        <option value="error">Error</option>
                        <option value="debug">Debug</option>
                    </select>
                </div>
                
                <div class="log-container p-2 bg-dark text-light rounded" style="height: 200px; overflow-y: auto; font-family: monospace; font-size: 0.8rem;">
                    <div>[INFO] 2023-01-15 12:30:45 - Application started successfully</div>
                    <div>[INFO] 2023-01-15 12:30:46 - Database connection established</div>
                    <div>[INFO] 2023-01-15 12:31:02 - User 'admin' logged in</div>
                    <div>[INFO] 2023-01-15 12:35:18 - New malware sample uploaded (SHA256: 8a9f...)</div>
                    <div>[INFO] 2023-01-15 12:40:33 - Detonation job #12 created</div>
                    <div>[INFO] 2023-01-15 12:40:35 - VM deployment initiated for job #12</div>
                    <div>[INFO] 2023-01-15 12:45:22 - Detonation job #12 completed</div>
                </div>
                
                <div class="d-grid gap-2 mt-3">
                    <button class="btn btn-outline-primary" onclick="refreshLogs()">
                        <i class="fas fa-sync"></i> Refresh Logs
                    </button>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}

{% block scripts %}
<script>
    function checkGCPResources() {
        alert('GCP resource verification initiated. This may take a moment...');
        // In a real implementation, this would make an AJAX call to a backend endpoint
    }
    
    function testVMDeployment() {
        alert('VM deployment test initiated. This may take a few minutes...');
        // In a real implementation, this would make an AJAX call to a backend endpoint
    }
    
    function refreshLogs() {
        alert('Refreshing logs...');
        // In a real implementation, this would make an AJAX call to get the latest logs
    }
</script>
{% endblock %}""",

        'diagnostic.html': """{% extends 'base.html' %}

{% block title %}Diagnostics - {{ app_name }}{% endblock %}

{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4">
    <h1>System Diagnostics</h1>
    <div>
        <a href="{{ url_for('web.index') }}" class="btn btn-outline-secondary">
            <i class="fas fa-arrow-left"></i> Back to Home
        </a>
    </div>
</div>

<div class="row">
    <div class="col-md-6">
        <div class="card mb-4">
            <div class="card-header bg-primary text-white">
                <h5 class="card-title mb-0">Application Information</h5>
            </div>
            <div class="card-body">
                <table class="table table-sm">
                    <tr>
                        <th width="30%">App Name:</th>
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
        
        <div class="card mb-4">
            <div class="card-header bg-primary text-white">
                <h5 class="card-title mb-0">Module Status</h5>
            </div>
            <div class="card-body">
                {% if diagnostics.module_status.error is defined %}
                    <div class="alert alert-danger">{{ diagnostics.module_status.error }}</div>
                {% else %}
                    <table class="table table-sm">
                        {% for module_name, module_info in diagnostics.module_status.items() %}
                            <tr>
                                <th width="30%">{{ module_name }}:</th>
                                <td>
                                    {% if module_info.initialized %}
                                        <span class="badge bg-success">Initialized</span>
                                    {% else %}
                                        <span class="badge bg-warning">Not Initialized</span>
                                    {% endif %}
                                    
                                    {% if module_info.error %}
                                        <span class="badge bg-danger">Error</span>
                                        <p class="text-danger small mt-1">{{ module_info.error }}</p>
                                    {% endif %}
                                </td>
                            </tr>
                        {% endfor %}
                    </table>
                {% endif %}
                
                <div class="mt-3">
                    <a href="{{ url_for('web.health') }}" class="btn btn-outline-primary btn-sm" target="_blank">
                        <i class="fas fa-heartbeat"></i> Health Check API
                    </a>
                </div>
            </div>
        </div>
    </div>
    
    <div class="col-md-6">
        <div class="card mb-4">
            <div class="card-header bg-primary text-white">
                <h5 class="card-title mb-0">Template Information</h5>
            </div>
            <div class="card-body">
                {% if diagnostics.template_info.error is defined %}
                    <div class="alert alert-danger">{{ diagnostics.template_info.error }}</div>
                {% else %}
                    <table class="table table-sm">
                        <tr>
                            <th width="30%">Templates Path:</th>
                            <td>{{ diagnostics.template_info.path }}</td>
                        </tr>
                        <tr>
                            <th>Directory Exists:</th>
                            <td>{{ diagnostics.template_info.exists }}</td>
                        </tr>
                        <tr>
                            <th>base.html Exists:</th>
                            <td>{{ diagnostics.template_info.base_exists }}</td>
                        </tr>
                        <tr>
                            <th>index.html Exists:</th>
                            <td>{{ diagnostics.template_info.index_exists }}</td>
                        </tr>
                    </table>
                    
                    {% if diagnostics.template_info.files %}
                        <h6 class="mt-3">Template Files:</h6>
                        <div class="border p-2 rounded" style="max-height: 150px; overflow-y: auto;">
                            <ul class="list-unstyled mb-0">
                                {% for file in diagnostics.template_info.files %}
                                    <li><i class="fas fa-file-code text-primary me-2"></i> {{ file }}</li>
                                {% endfor %}
                            </ul>
                        </div>
                    {% endif %}
                {% endif %}
                
                <div class="d-grid gap-2 mt-3">
                    <button class="btn btn-outline-primary" id="recreate-templates">
                        <i class="fas fa-sync"></i> Recreate Basic Templates
                    </button>
                </div>
            </div>
        </div>
        
        <div class="card">
            <div class="card-header bg-primary text-white">
                <h5 class="card-title mb-0">Database Information</h5>
            </div>
            <div class="card-body">
                {% if diagnostics.database_info.error is defined %}
                    <div class="alert alert-danger">{{ diagnostics.database_info.error }}</div>
                {% else %}
                    <table class="table table-sm">
                        <tr>
                            <th width="30%">Database Path:</th>
                            <td>{{ diagnostics.database_info.path }}</td>
                        </tr>
                        <tr>
                            <th>Database Exists:</th>
                            <td>{{ diagnostics.database_info.exists }}</td>
                        </tr>
                        {% if diagnostics.database_info.users_table_exists is defined %}
                            <tr>
                                <th>Users Table:</th>
                                <td>{{ diagnostics.database_info.users_table_exists }}</td>
                            </tr>
                        {% endif %}
                        {% if diagnostics.database_info.user_count is defined %}
                            <tr>
                                <th>User Count:</th>
                                <td>{{ diagnostics.database_info.user_count }}</td>
                            </tr>
                        {% endif %}
                    </table>
                {% endif %}
                
                <div class="d-grid gap-2 mt-3">
                    <button class="btn btn-outline-primary" id="init-database">
                        <i class="fas fa-database"></i> Initialize Database
                    </button>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}

{% block scripts %}
<script>
    document.addEventListener('DOMContentLoaded', function() {
        // Recreate templates button
        document.getElementById('recreate-templates').addEventListener('click', function() {
            if (confirm('Are you sure you want to recreate the basic templates?')) {
                fetch('/recreate-templates', { method: 'POST' })
                    .then(response => response.json())
                    .then(data => {
                        alert(data.message || 'Templates recreated. Refresh the page to see changes.');
                        window.location.reload();
                    })
                    .catch(error => {
                        alert('Error: ' + error);
                    });
            }
        });
        
        // Initialize database button
        document.getElementById('init-database').addEventListener('click', function() {
            if (confirm('Are you sure you want to initialize the database? This may reset existing data.')) {
                fetch('/init-database', { method: 'POST' })
                    .then(response => response.json())
                    .then(data => {
                        alert(data.message || 'Database initialized. Refresh the page to see changes.');
                        window.location.reload();
                    })
                    .catch(error => {
                        alert('Error: ' + error);
                    });
            }
        });
    });
</script>
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

    // Handle any forms with AJAX submission
    const ajaxForms = document.querySelectorAll('form[data-ajax="true"]');
    if (ajaxForms) {
        ajaxForms.forEach(form => {
            form.addEventListener('submit', function(e) {
                e.preventDefault();
                
                const formData = new FormData(form);
                const submitBtn = form.querySelector('button[type="submit"]');
                const originalBtnText = submitBtn.innerHTML;
                
                // Disable button and show loading state
                if (submitBtn) {
                    submitBtn.disabled = true;
                    submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Processing...';
                }
                
                // Send form data with fetch API
                fetch(form.action, {
                    method: form.method,
                    body: formData,
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                })
                .then(response => response.json())
                .then(data => {
                    // Handle response
                    if (data.success) {
                        if (data.redirect) {
                            window.location.href = data.redirect;
                        } else if (data.message) {
                            showAlert(data.message, 'success');
                        }
                    } else {
                        showAlert(data.message || 'An error occurred', 'danger');
                    }
                })
                .catch(error => {
                    console.error('Error submitting form:', error);
                    showAlert('An unexpected error occurred. Please try again.', 'danger');
                })
                .finally(() => {
                    // Reset button state
                    if (submitBtn) {
                        submitBtn.disabled = false;
                        submitBtn.innerHTML = originalBtnText;
                    }
                });
            });
        });
    }
    
    // Function to show alert messages
    function showAlert(message, type = 'info') {
        const alertsContainer = document.createElement('div');
        alertsContainer.className = 'alert-container';
        alertsContainer.style.position = 'fixed';
        alertsContainer.style.top = '20px';
        alertsContainer.style.right = '20px';
        alertsContainer.style.zIndex = '9999';
        
        const alert = document.createElement('div');
        alert.className = `alert alert-${type} alert-dismissible fade show`;
        alert.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        `;
        
        alertsContainer.appendChild(alert);
        document.body.appendChild(alertsContainer);
        
        setTimeout(() => {
            alert.classList.remove('show');
            setTimeout(() => {
                document.body.removeChild(alertsContainer);
            }, 300);
        }, 5000);
    }
});"""
    }
    
    try:
        # Create templates directory
        os.makedirs('templates', exist_ok=True)
        
        # Generate templates if they don't exist
        for template_name, template_content in templates_to_generate.items():
            if not os.path.exists(f'templates/{template_name}'):
                with open(f'templates/{template_name}', 'w') as f:
                    f.write(template_content)
                logger.info(f"Created template: {template_name}")
        
        # Create static files directories
        os.makedirs('static/css', exist_ok=True)
        os.makedirs('static/js', exist_ok=True)
        
        # Generate static files if they don't exist
        for filepath, content in static_files.items():
            if not os.path.exists(f'static/{filepath}'):
                os.makedirs(os.path.dirname(f'static/{filepath}'), exist_ok=True)
                with open(f'static/{filepath}', 'w') as f:
                    f.write(content)
                logger.info(f"Created static file: {filepath}")
                
        logger.info("All templates and static files generated successfully")
    except Exception as e:
        logger.error(f"Error generating templates: {e}")
