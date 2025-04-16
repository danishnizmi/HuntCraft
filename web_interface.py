from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, session, g
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import os
import json
import sqlite3
from datetime import datetime
import hashlib
import secrets
from functools import wraps

# Create blueprint
web_bp = Blueprint('web', __name__, url_prefix='')
login_manager = LoginManager()

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, id, username, email, role):
        self.id = id
        self.username = username
        self.email = email
        self.role = role

def init_app(app):
    """Initialize the web interface module with the Flask app"""
    app.register_blueprint(web_bp)
    
    # Initialize Flask-Login
    login_manager.init_app(app)
    login_manager.login_view = 'web.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'
    
    # User loader function for Flask-Login
    @login_manager.user_loader
    def load_user(user_id):
        return get_user_by_id(user_id)
    
    # Register context processors to make configuration available in templates
    @app.context_processor
    def inject_config():
        """Make configuration values available to templates"""
        return {
            'app_name': current_app.config['APP_NAME'],
            'colors': {
                'primary': current_app.config.get('PRIMARY_COLOR', '#4a6fa5'),
                'secondary': current_app.config.get('SECONDARY_COLOR', '#6c757d'),
                'danger': current_app.config.get('DANGER_COLOR', '#dc3545'),
                'success': current_app.config.get('SUCCESS_COLOR', '#28a745'),
                'warning': current_app.config.get('WARNING_COLOR', '#ffc107'),
                'info': current_app.config.get('INFO_COLOR', '#17a2b8'),
                'dark': current_app.config.get('DARK_COLOR', '#343a40'),
                'light': current_app.config.get('LIGHT_COLOR', '#f8f9fa')
            },
            'features': {
                'advanced_analysis': current_app.config.get('ENABLE_ADVANCED_ANALYSIS', True),
                'data_export': current_app.config.get('ENABLE_DATA_EXPORT', True),
                'visualization': current_app.config.get('ENABLE_VISUALIZATION', True)
            },
            'year': datetime.now().year,
            'user': current_user if not current_user.is_anonymous else None
        }

    # Register template filters
    @app.template_filter('format_date')
    def format_date(value):
        """Format a date for display"""
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace('Z', '+00:00'))
            except ValueError:
                return value
        if isinstance(value, datetime):
            return value.strftime('%Y-%m-%d')
        return value

    # Ensure base templates and static resources exist
    if app.config.get('GENERATE_TEMPLATES', False):
        generate_base_templates()
        generate_css()
        generate_js()

# Database schema related functions
def create_database_schema(cursor):
    """Create the necessary database tables for the web interface module"""
    # Create users table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        email TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL,
        role TEXT DEFAULT 'analyst',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_login TIMESTAMP
    )
    ''')
    
    # Create user_settings table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        setting_key TEXT NOT NULL,
        setting_value TEXT,
        FOREIGN KEY (user_id) REFERENCES users(id),
        UNIQUE(user_id, setting_key)
    )
    ''')
    
    # Create an admin user if no users exist
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    
    if count == 0:
        # Create default admin user with more secure random password
        admin_password = secrets.token_urlsafe(12)  # Generate a secure random password
        salt = secrets.token_hex(8)
        password_hash = hashlib.sha256(f"{admin_password}{salt}".encode()).hexdigest()
        
        cursor.execute(
            "INSERT INTO users (username, email, password, role) VALUES (?, ?, ?, ?)",
            ("admin", "admin@threathunting.local", f"{salt}:{password_hash}", "admin")
        )
        
        # Log the initial password so it can be retrieved from logs
        import logging
        logging.getLogger(__name__).info(f"Created initial admin user with password: {admin_password}")

# Helper function for DB connections
def _db_connection(row_factory=None):
    """Create a database connection with optional row factory"""
    conn = sqlite3.connect(current_app.config['DATABASE_PATH'])
    if row_factory:
        conn.row_factory = row_factory
    return conn

# User functions
def get_user_by_id(user_id):
    """Get a user by ID"""
    conn = _db_connection(sqlite3.Row)
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user_data = cursor.fetchone()
    
    conn.close()
    
    if user_data:
        user = User(
            id=user_data['id'],
            username=user_data['username'],
            email=user_data['email'],
            role=user_data['role']
        )
        return user
    return None

def get_user_by_username(username):
    """Get a user by username"""
    conn = _db_connection(sqlite3.Row)
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    user_data = cursor.fetchone()
    
    conn.close()
    
    return dict(user_data) if user_data else None

def validate_login(username, password):
    """Validate user login credentials"""
    user_data = get_user_by_username(username)
    if not user_data:
        return None
    
    # Extract salt and stored hash
    stored_password = user_data['password']
    if ':' not in stored_password:
        return None  # Invalid password format
    
    salt, stored_hash = stored_password.split(':', 1)
    
    # Compute hash with provided password and stored salt
    computed_hash = hashlib.sha256(f"{password}{salt}".encode()).hexdigest()
    
    if computed_hash == stored_hash:
        # Update last login time
        conn = _db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET last_login = datetime('now') WHERE id = ?", 
            (user_data['id'],)
        )
        conn.commit()
        conn.close()
        
        return User(
            id=user_data['id'],
            username=user_data['username'],
            email=user_data['email'],
            role=user_data['role']
        )
    return None

def create_user(username, email, password, role='analyst'):
    """Create a new user account"""
    salt = secrets.token_hex(8)
    password_hash = hashlib.sha256(f"{password}{salt}".encode()).hexdigest()
    
    conn = _db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "INSERT INTO users (username, email, password, role) VALUES (?, ?, ?, ?)",
            (username, email, f"{salt}:{password_hash}", role)
        )
        conn.commit()
        user_id = cursor.lastrowid
        conn.close()
        return user_id
    except sqlite3.IntegrityError:
        conn.rollback()
        conn.close()
        return None

# Role-based access control
def admin_required(f):
    """Decorator for views that require admin access"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.is_anonymous or current_user.role != 'admin':
            flash('Admin privileges required to access this page.', 'warning')
            return redirect(url_for('web.index'))
        return f(*args, **kwargs)
    return decorated_function

# Basic routes
@web_bp.route('/')
def index():
    """Home page"""
    return render_template('index.html')

@web_bp.route('/dashboard')
@login_required
def dashboard():
    """Dashboard page - with lazy loading of modules"""
    # Prepare empty data containers
    user_datasets = []
    user_analyses = []
    user_visualizations = []
    
    try:
        # Lazy load modules only when needed
        from main import get_module
        
        # Try getting datasets from malware module
        malware_module = get_module('malware')
        if malware_module and hasattr(malware_module, 'get_datasets'):
            user_datasets = malware_module.get_datasets()
        
        # Try getting analyses from detonation or analysis module
        detonation_module = get_module('detonation')
        if detonation_module and hasattr(detonation_module, 'get_saved_queries'):
            user_analyses = detonation_module.get_saved_queries()
        
        # Get visualizations if available
        viz_module = get_module('viz')
        if viz_module and hasattr(viz_module, 'get_visualizations_for_dashboard'):
            user_visualizations = viz_module.get_visualizations_for_dashboard()
    except Exception as e:
        flash(f"Some dashboard components could not be loaded", "warning")
    
    return render_template(
        'dashboard.html',
        datasets=user_datasets[:5],
        analyses=user_analyses[:5],
        visualizations=user_visualizations[:5]
    )

@web_bp.route('/about')
def about():
    """About page"""
    return render_template('about.html')

@web_bp.route('/health')
def health():
    """Health check endpoint for Cloud Run"""
    return {'status': 'ok', 'timestamp': datetime.now().isoformat()}

# Authentication routes
@web_bp.route('/login', methods=['GET', 'POST'])
def login():
    """User login form and handler"""
    if current_user.is_authenticated:
        return redirect(url_for('web.dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = 'remember' in request.form
        
        user = validate_login(username, password)
        
        if user:
            login_user(user, remember=remember)
            flash('Login successful!', 'success')
            
            # Redirect to requested page or dashboard
            next_page = request.args.get('next')
            if next_page and next_page.startswith('/'):  # Ensure URL is relative
                return redirect(next_page)
            return redirect(url_for('web.dashboard'))
        else:
            flash('Invalid username or password', 'danger')
    
    return render_template('login.html')

@web_bp.route('/logout')
@login_required
def logout():
    """User logout handler"""
    logout_user()
    flash('You have been logged out', 'info')
    return redirect(url_for('web.index'))

@web_bp.route('/register', methods=['GET', 'POST'])
def register():
    """User registration form and handler"""
    if current_user.is_authenticated:
        return redirect(url_for('web.dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        password_confirm = request.form.get('password_confirm')
        
        # Basic validation
        if len(username) < 3:
            flash('Username must be at least 3 characters', 'danger')
        elif len(password) < 6:
            flash('Password must be at least 6 characters', 'danger')
        elif password != password_confirm:
            flash('Passwords do not match', 'danger')
        else:
            # Create new user
            user_id = create_user(username, email, password)
            
            if user_id:
                flash('Account created successfully! You can now log in.', 'success')
                return redirect(url_for('web.login'))
            else:
                flash('Username or email already exists', 'danger')
    
    return render_template('register.html')

@web_bp.route('/profile')
@login_required
def profile():
    """User profile page"""
    return render_template('profile.html')

@web_bp.route('/admin')
@login_required
@admin_required
def admin():
    """Admin dashboard"""
    # Get all users - with pagination for efficiency
    page = request.args.get('page', 1, type=int)
    page_size = 20
    offset = (page - 1) * page_size
    
    conn = _db_connection(sqlite3.Row)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?", 
                  (page_size, offset))
    users = [dict(row) for row in cursor.fetchall()]
    
    # Get total count for pagination
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    conn.close()
    
    return render_template('admin.html', 
                          users=users,
                          page=page,
                          total_pages=(total_users + page_size - 1) // page_size)

# Error handlers
def handle_404():
    """Handle 404 errors"""
    return render_template('404.html') if os.path.exists('templates/404.html') else "Page not found", 404

def handle_500():
    """Handle 500 errors"""
    return render_template('500.html') if os.path.exists('templates/500.html') else "Server error", 500

# Static file generators - only run when explicitly requested
def generate_css():
    """Generate CSS for the web interface"""
    # Skip if already exists
    if os.path.exists('static/css/main.css'):
        return
        
    os.makedirs('static/css', exist_ok=True)
    
    # Main CSS file - minimal version
    main_css = """
    /* Main application styling - Minimal version */
    :root {
        --primary-color: """ + current_app.config.get('PRIMARY_COLOR', '#4a6fa5') + """;
        --secondary-color: """ + current_app.config.get('SECONDARY_COLOR', '#6c757d') + """;
        --danger-color: """ + current_app.config.get('DANGER_COLOR', '#dc3545') + """;
        --success-color: """ + current_app.config.get('SUCCESS_COLOR', '#28a745') + """;
    }

    body { font-family: 'Helvetica Neue', Arial, sans-serif; color: #333; background-color: #f8f9fa; line-height: 1.6; }
    .main-content { flex: 1; }
    .navbar { background-color: var(--primary-color); box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
    .navbar-brand { font-weight: 700; color: white !important; }
    .card { box-shadow: 0 2px 4px rgba(0,0,0,0.1); border: none; border-radius: 0.5rem; margin-bottom: 1rem; }
    .auth-card { max-width: 500px; margin: 2rem auto; }
    .auth-header { text-align: center; margin-bottom: 1.5rem; }
    .footer { background-color: #343a40; color: white; padding: 1rem 0; margin-top: 2rem; }
    """
    
    with open('static/css/main.css', 'w') as f:
        f.write(main_css)

def generate_js():
    """Generate JavaScript for the web interface"""
    # Skip if already exists
    if os.path.exists('static/js/main.js'):
        return
        
    os.makedirs('static/js', exist_ok=True)
    
    # Main JS file - minimal version
    main_js = """
    // Main application JavaScript - Minimal version
    document.addEventListener('DOMContentLoaded', function() {
        // Handle flash messages auto-dismiss
        const flashMessages = document.querySelectorAll('.alert-dismissible');
        flashMessages.forEach(message => {
            setTimeout(() => {
                if (message.parentNode) {
                    message.style.opacity = '0';
                    setTimeout(() => message.remove(), 500);
                }
            }, 5000);
        });
    });
    """
    
    with open('static/js/main.js', 'w') as f:
        f.write(main_js)

def generate_base_templates():
    """Generate the base HTML templates for the application"""
    # Skip if templates already exist
    if os.path.exists('templates/base.html') and os.path.exists('templates/index.html'):
        return
        
    os.makedirs('templates', exist_ok=True)
    
    # Create base template
    base_html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{% block title %}{{ app_name }}{% endblock %}</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
        <link href="{{ url_for('static', filename='css/main.css') }}" rel="stylesheet">
        {% block styles %}{% endblock %}
    </head>
    <body>
        <nav class="navbar navbar-expand-lg navbar-dark">
            <div class="container">
                <a class="navbar-brand" href="{{ url_for('web.index') }}">{{ app_name }}</a>
                <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
                    <span class="navbar-toggler-icon"></span>
                </button>
                <div class="collapse navbar-collapse" id="navbarNav">
                    <ul class="navbar-nav me-auto">
                        {% if current_user.is_authenticated %}
                        <li class="nav-item">
                            <a class="nav-link" href="{{ url_for('web.dashboard') }}">Dashboard</a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="{{ url_for('malware.index') }}">Malware</a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="{{ url_for('detonation.index') }}">Detonation</a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="{{ url_for('viz.index') }}">Visualizations</a>
                        </li>
                        {% endif %}
                        <li class="nav-item">
                            <a class="nav-link" href="{{ url_for('web.about') }}">About</a>
                        </li>
                    </ul>
                    <ul class="navbar-nav">
                        {% if current_user.is_authenticated %}
                        <li class="nav-item dropdown">
                            <a class="nav-link dropdown-toggle" href="#" id="userDropdown" role="button" data-bs-toggle="dropdown">
                                {{ current_user.username }}
                            </a>
                            <ul class="dropdown-menu dropdown-menu-end">
                                <li><a class="dropdown-item" href="{{ url_for('web.profile') }}">Profile</a></li>
                                {% if current_user.role == 'admin' %}
                                <li><a class="dropdown-item" href="{{ url_for('web.admin') }}">Admin</a></li>
                                {% endif %}
                                <li><hr class="dropdown-divider"></li>
                                <li><a class="dropdown-item" href="{{ url_for('web.logout') }}">Logout</a></li>
                            </ul>
                        </li>
                        {% else %}
                        <li class="nav-item">
                            <a class="nav-link" href="{{ url_for('web.login') }}">Login</a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="{{ url_for('web.register') }}">Register</a>
                        </li>
                        {% endif %}
                    </ul>
                </div>
            </div>
        </nav>

        <main class="main-content">
            {% block content %}{% endblock %}
        </main>

        <footer class="footer">
            <div class="container">
                <div class="text-center">
                    <p>&copy; {{ year }} {{ app_name }}</p>
                </div>
            </div>
        </footer>

        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
        <script src="{{ url_for('static', filename='js/main.js') }}"></script>
        {% block scripts %}{% endblock %}
    </body>
    </html>
    """
    
    # Create a minimal index template
    index_html = """
    {% extends 'base.html' %}
    
    {% block title %}{{ app_name }} - Home{% endblock %}
    
    {% block content %}
    <div class="container mt-5">
        <div class="row justify-content-center">
            <div class="col-lg-8 text-center">
                <h1>{{ app_name }}</h1>
                <p class="lead">A platform for security analysts to analyze and detonate malware samples</p>
                
                {% if not current_user.is_authenticated %}
                <div class="mt-4">
                    <a href="{{ url_for('web.login') }}" class="btn btn-primary me-2">Login</a>
                    <a href="{{ url_for('web.register') }}" class="btn btn-outline-primary">Register</a>
                </div>
                {% else %}
                <div class="mt-4">
                    <a href="{{ url_for('web.dashboard') }}" class="btn btn-primary me-2">Go to Dashboard</a>
                    <a href="{{ url_for('malware.upload') }}" class="btn btn-outline-primary">Upload Malware</a>
                </div>
                {% endif %}
            </div>
        </div>
    </div>
    {% endblock %}
    """
    
    # Create a minimal login template
    login_html = """
    {% extends 'base.html' %}
    
    {% block title %}Login - {{ app_name }}{% endblock %}
    
    {% block content %}
    <div class="container mt-5">
        <div class="row justify-content-center">
            <div class="col-md-6">
                <div class="card auth-card">
                    <div class="card-body">
                        <div class="auth-header">
                            <h2>Login</h2>
                        </div>
                        
                        {% with messages = get_flashed_messages(with_categories=true) %}
                          {% if messages %}
                            {% for category, message in messages %}
                              <div class="alert alert-{{ category }}">{{ message }}</div>
                            {% endfor %}
                          {% endif %}
                        {% endwith %}
                        
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
                            <div class="d-grid">
                                <button type="submit" class="btn btn-primary">Login</button>
                            </div>
                        </form>
                        
                        <div class="text-center mt-3">
                            <p>Don't have an account? <a href="{{ url_for('web.register') }}">Register</a></p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    {% endblock %}
    """
    
    # Write templates to files
    with open('templates/base.html', 'w') as f:
        f.write(base_html)
        
    with open('templates/index.html', 'w') as f:
        f.write(index_html)
        
    with open('templates/login.html', 'w') as f:
        f.write(login_html)
