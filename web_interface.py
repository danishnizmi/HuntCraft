from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, g, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import sqlite3, json, os, datetime, logging
from functools import wraps
from werkzeug.security import check_password_hash, generate_password_hash

# Create blueprint and initialize logger
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
    app.register_blueprint(web_bp)
    
    # Setup login manager
    login_manager.init_app(app)
    login_manager.login_view = 'web.login'
    
    # Generate necessary templates and static files
    with app.app_context():
        generate_base_templates()
        
        # Register template filters
        @app.template_filter('format_file_size')
        def format_file_size(size):
            """Format file size in bytes to a readable format"""
            if not size:
                return "0 bytes"
            size = int(size)
            for unit in ['bytes', 'KB', 'MB', 'GB', 'TB']:
                if size < 1024.0:
                    return f"{size:.1f} {unit}"
                size /= 1024.0
            return f"{size:.1f} PB"
            
        # Register context processors
        @app.context_processor
        def inject_common_variables():
            """Inject common variables into all templates"""
            return {
                'app_name': app.config.get('APP_NAME', 'Malware Detonation Platform'),
                'colors': {
                    'primary': app.config.get('PRIMARY_COLOR', '#4a6fa5'),
                    'secondary': app.config.get('SECONDARY_COLOR', '#6c757d'),
                    'danger': app.config.get('DANGER_COLOR', '#dc3545'),
                    'success': app.config.get('SUCCESS_COLOR', '#28a745'),
                    'warning': app.config.get('WARNING_COLOR', '#ffc107'),
                    'info': app.config.get('INFO_COLOR', '#17a2b8'),
                    'dark': app.config.get('DARK_COLOR', '#343a40'),
                    'light': app.config.get('LIGHT_COLOR', '#f8f9fa')
                },
                'year': datetime.datetime.now().year
            }

@login_manager.user_loader
def load_user(user_id):
    """Load user by ID"""
    conn = _db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, role FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    
    if user:
        return User(user[0], user[1], user[2])
    return None

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
    conn = sqlite3.connect(current_app.config['DATABASE_PATH'])
    if row_factory:
        conn.row_factory = row_factory
    return conn

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
    if current_user.is_authenticated:
        return redirect(url_for('web.dashboard'))
        
    if request.method == 'POST':
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
        
        flash('Invalid username or password', 'danger')
    
    return render_template('login.html')

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
    try:
        from malware_module import get_recent_samples
        datasets = get_recent_samples(5)
    except Exception as e:
        logger.error(f"Error loading recent samples: {e}")
        datasets = []
        
    try:
        from detonation_module import get_detonation_jobs
        analyses = get_detonation_jobs()[:5]
    except Exception as e:
        logger.error(f"Error loading detonation jobs: {e}")
        analyses = []
    
    try:
        from viz_module import get_visualizations_for_dashboard
        visualizations = get_visualizations_for_dashboard()
    except Exception as e:
        logger.error(f"Error loading visualizations: {e}")
        visualizations = []
    
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
    conn = _db_connection(sqlite3.Row)
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, role, created_at FROM users ORDER BY id")
    users_list = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
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
        
        # Check if username already exists
        conn = _db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        if cursor.fetchone():
            conn.close()
            flash('Username already exists', 'danger')
            return redirect(url_for('web.add_user'))
        
        # Create new user
        try:
            cursor.execute(
                "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                (username, generate_password_hash(password), role)
            )
            conn.commit()
            flash('User created successfully', 'success')
            return redirect(url_for('web.users'))
        except Exception as e:
            conn.rollback()
            flash(f'Error creating user: {str(e)}', 'danger')
        finally:
            conn.close()
    
    return render_template('user_form.html', user=None)

@web_bp.route('/users/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(user_id):
    """Edit user - admin only"""
    conn = _db_connection(sqlite3.Row)
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, role FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        conn.close()
        flash('User not found', 'danger')
        return redirect(url_for('web.users'))
    
    user = dict(user)
    
    if request.method == 'POST':
        role = request.form.get('role', 'analyst')
        password = request.form.get('password')
        
        update_fields = ["role = ?"]
        update_values = [role]
        
        if password:
            update_fields.append("password = ?")
            update_values.append(generate_password_hash(password))
        
        update_values.append(user_id)
        
        try:
            cursor.execute(
                f"UPDATE users SET {', '.join(update_fields)} WHERE id = ?",
                update_values
            )
            conn.commit()
            flash('User updated successfully', 'success')
            return redirect(url_for('web.users'))
        except Exception as e:
            conn.rollback()
            flash(f'Error updating user: {str(e)}', 'danger')
    
    conn.close()
    return render_template('user_form.html', user=user)

@web_bp.route('/users/delete/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    """Delete user - admin only"""
    # Prevent deleting the current user
    if user_id == current_user.id:
        flash('You cannot delete your own account', 'danger')
        return redirect(url_for('web.users'))
    
    conn = _db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        flash('User deleted successfully', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error deleting user: {str(e)}', 'danger')
    finally:
        conn.close()
    
    return redirect(url_for('web.users'))

@web_bp.route('/api/app-info')
def api_app_info():
    """API endpoint for basic app info"""
    return jsonify({
        'name': current_app.config.get('APP_NAME', 'Malware Detonation Platform'),
        'version': current_app.config.get('APP_VERSION', '1.0.0'),
        'environment': current_app.config.get('ENVIRONMENT', 'production')
    })

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
                
                <h4>Account Information</h4>
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

        'users.html': """{% extends 'base.html' %}

{% block title %}User Management - {{ app_name }}{% endblock %}

{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4">
    <h1>User Management</h1>
    <a href="{{ url_for('web.add_user') }}" class="btn btn-primary">
        <i class="fas fa-plus"></i> Add User
    </a>
</div>

<div class="card">
    <div class="card-header bg-primary text-white">
        <h5 class="card-title mb-0">Users</h5>
    </div>
    <div class="card-body">
        {% if users %}
            <div class="table-responsive">
                <table class="table table-striped table-hover">
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
                            <td>
                                <span class="badge bg-{% if user.role == 'admin' %}danger{% else %}primary{% endif %}">
                                    {{ user.role }}
                                </span>
                            </td>
                            <td>{{ user.created_at }}</td>
                            <td>
                                <a href="{{ url_for('web.edit_user', user_id=user.id) }}" class="btn btn-sm btn-info">
                                    <i class="fas fa-edit"></i>
                                </a>
                                
                                {% if user.id != current_user.id %}
                                <form method="POST" action="{{ url_for('web.delete_user', user_id=user.id) }}" class="d-inline">
                                    <button type="submit" class="btn btn-sm btn-danger" data-confirm="Are you sure you want to delete this user?">
                                        <i class="fas fa-trash"></i>
                                    </button>
                                </form>
                                {% endif %}
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        {% else %}
            <div class="alert alert-info">No users found.</div>
        {% endif %}
    </div>
</div>
{% endblock %}""",

        'user_form.html': """{% extends 'base.html' %}

{% block title %}{% if user %}Edit User{% else %}Add User{% endif %} - {{ app_name }}{% endblock %}

{% block content %}
<div class="row justify-content-center">
    <div class="col-md-8">
        <div class="card">
            <div class="card-header bg-primary text-white">
                <h2 class="card-title">{% if user %}Edit User{% else %}Add User{% endif %}</h2>
            </div>
            <div class="card-body">
                <form method="POST">
                    {% if not user %}
                    <div class="mb-3">
                        <label for="username" class="form-label">Username</label>
                        <input type="text" class="form-control" id="username" name="username" required>
                    </div>
                    {% else %}
                    <div class="mb-3">
                        <label class="form-label">Username</label>
                        <input type="text" class="form-control" value="{{ user.username }}" disabled>
                    </div>
                    {% endif %}
                    
                    <div class="mb-3">
                        <label for="password" class="form-label">{% if user %}New Password (leave blank to keep current){% else %}Password{% endif %}</label>
                        <input type="password" class="form-control" id="password" name="password" {% if not user %}required{% endif %}>
                    </div>
                    
                    <div class="mb-3">
                        <label for="role" class="form-label">Role</label>
                        <select class="form-select" id="role" name="role" required>
                            <option value="analyst" {% if user and user.role == 'analyst' %}selected{% endif %}>Analyst</option>
                            <option value="admin" {% if user and user.role == 'admin' %}selected{% endif %}>Administrator</option>
                        </select>
                    </div>
                    
                    <div class="d-flex justify-content-between">
                        <a href="{{ url_for('web.users') }}" class="btn btn-secondary">Cancel</a>
                        <button type="submit" class="btn btn-primary">{% if user %}Update{% else %}Create{% endif %} User</button>
                    </div>
                </form>
            </div>
        </div>
    </div>
</div>
{% endblock %}"""
    }
    
    static_files = {
        'css/main.css': """/* Main CSS styles */
body { font-family: 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #333; background-color: #f8f9fa; }
.card { box-shadow: 0 2px 4px rgba(0,0,0,0.05); margin-bottom: 20px; border: none; border-radius: 8px; }
.card-header { border-top-left-radius: 8px !important; border-top-right-radius: 8px !important; }
.dashboard-stat { padding: 20px; text-align: center; }
.dashboard-stat i { font-size: 2rem; margin-bottom: 10px; }
.dashboard-stat h3 { font-size: 1.8rem; margin-bottom: 5px; }
.hash-value { font-family: monospace; word-break: break-all; }
.table-responsive { overflow-x: auto; }
.tag-badge { background-color: #e9ecef; color: #333; padding: 3px 8px; border-radius: 12px; font-size: 0.8rem; margin-right: 5px; margin-bottom: 5px; display: inline-block; }
.detail-row { border-bottom: 1px solid #e9ecef; padding: 8px 0; }
.detail-label { font-weight: bold; }
.viz-container { height: 500px; width: 100%; border-radius: 4px; border: 1px solid #e9ecef; margin-bottom: 20px; }
.viz-fullscreen { position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; z-index: 1050; background: white; padding: 20px; border-radius: 0; }
footer { margin-top: 50px; padding: 20px 0; border-top: 1px solid #e9ecef; }
.status-badge { padding: 5px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: bold; text-transform: uppercase; }
.status-queued { background-color: #f8f9fa; color: #6c757d; }
.status-running { background-color: #cff4fc; color: #0dcaf0; }
.status-completed { background-color: #d1e7dd; color: #198754; }
.status-failed { background-color: #f8d7da; color: #dc3545; }
.status-cancelled { background-color: #fff3cd; color: #ffc107; }
.loader { border: 4px solid #f3f3f3; border-top: 4px solid #3498db; border-radius: 50%; width: 30px; height: 30px; animation: spin 1s linear infinite; margin: 20px auto; }
@keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }""",
        
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
    
    // Status refresh for detonation jobs
    const statusElements = document.querySelectorAll('[data-job-id]');
    if (statusElements.length > 0) {
        const refreshStatus = function() {
            statusElements.forEach(el => {
                const jobId = el.getAttribute('data-job-id');
                fetch(`/detonation/api/status/${jobId}`)
                    .then(response => response.json())
                    .then(data => {
                        el.textContent = data.status;
                        el.className = `badge ${'bg-' + (data.status === 'completed' ? 'success' : data.status === 'failed' ? 'danger' : data.status === 'running' ? 'primary' : 'secondary')}`;
                        if (['completed', 'failed'].includes(data.status) && 
                            el.getAttribute('data-refresh-on-complete') === 'true') {
                            window.location.reload();
                        }
                    })
                    .catch(error => console.error('Error fetching status:', error));
            });
        };
        refreshStatus();
        setInterval(refreshStatus, 10000);
    }
    
    // Health check
    setInterval(function() {
        fetch('/health').then(response => response.json()).catch(error => {});
    }, 30000);
});"""
    }
    
    # Create templates
    os.makedirs('templates', exist_ok=True)
    for filename, content in templates_to_generate.items():
        if not os.path.exists(f'templates/{filename}'):
            with open(f'templates/{filename}', 'w') as f:
                f.write(content)
            logger.info(f"Created template: {filename}")
    
    # Create static files
    for filepath, content in static_files.items():
        directory = os.path.dirname(f'static/{filepath}')
        os.makedirs(directory, exist_ok=True)
        if not os.path.exists(f'static/{filepath}'):
            with open(f'static/{filepath}', 'w') as f:
                f.write(content)
            logger.info(f"Created static file: {filepath}")
