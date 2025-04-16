from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, g, jsonify, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import sqlite3, json, os, datetime, logging
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash

# Create blueprint and set up logging
web_bp = Blueprint('web', __name__, url_prefix='')
login_manager = LoginManager()
logger = logging.getLogger(__name__)

class User(UserMixin):
    def __init__(self, id, username, role):
        self.id = id
        self.username = username
        self.role = role

def init_app(app):
    """Initialize web interface module with Flask app"""
    # Set up exception handling
    app.errorhandler(500)(handle_server_error)
    app.errorhandler(404)(handle_not_found)
    
    # Register blueprint
    app.register_blueprint(web_bp)
    
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

def handle_server_error(e):
    """Handle 500 errors gracefully"""
    logger.error(f"Server error: {str(e)}")
    return render_template('error.html', 
                          error_code=500,
                          error_message="The server encountered an internal error. Please try again later."), 500

def handle_not_found(e):
    """Handle 404 errors gracefully"""
    return render_template('error.html',
                          error_code=404,
                          error_message="The requested page was not found."), 404

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
    return render_template('index.html')

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
            from malware_module import get_recent_samples
            datasets = get_recent_samples(5)
        except Exception as e:
            logger.error(f"Error loading recent samples: {e}")
        
        try:
            from detonation_module import get_detonation_jobs
            analyses = get_detonation_jobs()[:5] if len(get_detonation_jobs()) > 0 else []
        except Exception as e:
            logger.error(f"Error loading detonation jobs: {e}")
        
        try:
            from viz_module import get_visualizations_for_dashboard
            visualizations = get_visualizations_for_dashboard()
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

@web_bp.route('/health')
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy"}), 200

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
                <a href="/" class="btn btn-primary mt-3">Return to Home</a>
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
            .catch(error => console.error('Health check error:', error));
    }, 30000);
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
        raise
