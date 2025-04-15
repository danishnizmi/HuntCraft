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
                'primary': current_app.config['PRIMARY_COLOR'],
                'secondary': current_app.config['SECONDARY_COLOR'],
                'danger': current_app.config['DANGER_COLOR'],
                'success': current_app.config['SUCCESS_COLOR'],
                'warning': current_app.config['WARNING_COLOR'],
                'info': current_app.config['INFO_COLOR'],
                'dark': current_app.config['DARK_COLOR'],
                'light': current_app.config['LIGHT_COLOR']
            },
            'features': {
                'advanced_analysis': current_app.config['ENABLE_ADVANCED_ANALYSIS'],
                'data_export': current_app.config['ENABLE_DATA_EXPORT'],
                'visualization': current_app.config['ENABLE_VISUALIZATION']
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

    @app.template_filter('format_datetime')
    def format_datetime(value):
        """Format a datetime for display"""
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value.replace('Z', '+00:00'))
            except ValueError:
                return value
        if isinstance(value, datetime):
            return value.strftime('%Y-%m-%d %H:%M:%S')
        return value

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
        # Create default admin user
        salt = secrets.token_hex(8)
        password_hash = hashlib.sha256(f"admin123{salt}".encode()).hexdigest()
        
        cursor.execute(
            "INSERT INTO users (username, email, password, role) VALUES (?, ?, ?, ?)",
            ("admin", "admin@threathunting.local", f"{salt}:{password_hash}", "admin")
        )

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
    """Dashboard page"""
    # Get user-specific data for dashboard
    user_datasets = []
    user_analyses = []
    user_visualizations = []
    
    try:
        # Get user's datasets
        from data_module import get_datasets
        all_datasets = get_datasets()
        user_datasets = all_datasets[:3]  # Just showing 3 most recent for demo
        
        # Get user's analyses
        from analysis_module import get_saved_queries
        all_queries = get_saved_queries()
        user_analyses = all_queries[:3]  # Just showing 3 most recent for demo
        
        # Get user's visualizations
        from viz_module import get_visualizations
        all_visualizations = get_visualizations()
        user_visualizations = all_visualizations[:3]  # Just showing 3 most recent for demo
    except Exception as e:
        flash(f"Error loading dashboard data: {str(e)}", "error")
    
    return render_template(
        'dashboard.html',
        datasets=user_datasets,
        analyses=user_analyses,
        visualizations=user_visualizations
    )

@web_bp.route('/about')
def about():
    """About page"""
    return render_template('about.html')

@web_bp.route('/health')
def health():
    """Health check endpoint for Render"""
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
    # Get all users
    conn = _db_connection(sqlite3.Row)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users ORDER BY created_at DESC")
    users = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return render_template('admin.html', users=users)

# Error handlers
def handle_404():
    """Handle 404 errors"""
    return render_template('404.html')

def handle_500():
    """Handle 500 errors"""
    return render_template('500.html')

# Static file generators
def generate_css():
    """Generate CSS for the web interface"""
    os.makedirs('static/css', exist_ok=True)
    
    # Main CSS file
    main_css = """
    /* Main application styling */
    :root {
        --primary-color: """ + current_app.config['PRIMARY_COLOR'] + """;
        --secondary-color: """ + current_app.config['SECONDARY_COLOR'] + """;
        --danger-color: """ + current_app.config['DANGER_COLOR'] + """;
        --success-color: """ + current_app.config['SUCCESS_COLOR'] + """;
        --warning-color: """ + current_app.config['WARNING_COLOR'] + """;
        --info-color: """ + current_app.config['INFO_COLOR'] + """;
        --dark-color: """ + current_app.config['DARK_COLOR'] + """;
        --light-color: """ + current_app.config['LIGHT_COLOR'] + """;
    }

    body {
        font-family: 'Roboto', 'Helvetica Neue', Arial, sans-serif;
        color: #333;
        background-color: #f8f9fa;
        line-height: 1.6;
        min-height: 100vh;
        display: flex;
        flex-direction: column;
    }
    
    .main-content {
        flex: 1;
    }
    
    .navbar {
        background-color: var(--primary-color);
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    
    .navbar-brand {
        font-weight: 700;
        color: white !important;
    }
    
    .navbar-dark .navbar-nav .nav-link {
        color: rgba(255,255,255,0.8);
    }
    
    .navbar-dark .navbar-nav .nav-link:hover {
        color: white;
    }
    
    .card {
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        border: none;
        border-radius: 0.5rem;
        margin-bottom: 1.5rem;
    }
    
    .card-header {
        background-color: white;
        border-bottom: 1px solid #eaeaea;
        font-weight: 600;
    }
    
    .btn-primary {
        background-color: var(--primary-color);
        border-color: var(--primary-color);
    }
    
    .btn-secondary {
        background-color: var(--secondary-color);
        border-color: var(--secondary-color);
    }
    
    .btn-danger {
        background-color: var(--danger-color);
        border-color: var(--danger-color);
    }
    
    .btn-success {
        background-color: var(--success-color);
        border-color: var(--success-color);
    }
    
    .footer {
        background-color: var(--dark-color);
        color: white;
        padding: 2rem 0;
        margin-top: 3rem;
    }
    
    /* Auth forms */
    .auth-card {
        max-width: 500px;
        margin: 2rem auto;
    }
    
    .auth-header {
        text-align: center;
        margin-bottom: 1.5rem;
    }
    
    .auth-header i {
        font-size: 3rem;
        color: var(--primary-color);
        margin-bottom: 1rem;
        display: block;
    }
    
    .auth-footer {
        text-align: center;
        margin-top: 1rem;
    }
    
    /* User profile */
    .profile-header {
        background-color: var(--primary-color);
        color: white;
        padding: 2rem 0;
        margin-bottom: 2rem;
    }
    
    .profile-avatar {
        width: 120px;
        height: 120px;
        border-radius: 50%;
        background-color: white;
        display: flex;
        align-items: center;
        justify-content: center;
        margin: 0 auto 1rem;
        font-size: 3rem;
        color: var(--primary-color);
    }
    
    /* Dashboard specific styles */
    .stats-card {
        text-align: center;
        padding: 1.5rem;
    }
    
    .stats-card .stats-icon {
        font-size: 2.5rem;
        margin-bottom: 1rem;
        color: var(--primary-color);
    }
    
    .stats-card .stats-number {
        font-size: 1.8rem;
        font-weight: 700;
        margin-bottom: 0.5rem;
    }
    
    .stats-card .stats-title {
        color: #6c757d;
        font-size: 0.9rem;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    
    /* Sidebar */
    .sidebar {
        min-height: calc(100vh - 56px);
        background-color: var(--dark-color);
        padding-top: 1rem;
    }
    
    .sidebar .nav-link {
        color: rgba(255,255,255,0.8);
        padding: 0.8rem 1rem;
        display: flex;
        align-items: center;
    }
    
    .sidebar .nav-link:hover {
        color: white;
        background-color: rgba(255,255,255,0.1);
    }
    
    .sidebar .nav-link i {
        margin-right: 0.5rem;
        width: 20px;
        text-align: center;
    }
    
    .sidebar .nav-link.active {
        background-color: var(--primary-color);
        color: white;
    }
    
    /* User badge in navbar */
    .user-badge {
        background-color: rgba(255,255,255,0.2);
        padding: 0.25rem 0.5rem;
        border-radius: 0.25rem;
        margin-left: 0.5rem;
    }
    
    /* Responsive adjustments */
    @media (max-width: 768px) {
        .sidebar {
            min-height: auto;
        }
    }
    """
    
    with open('static/css/main.css', 'w') as f:
        f.write(main_css)

def generate_js():
    """Generate JavaScript for the web interface"""
    os.makedirs('static/js', exist_ok=True)
    
    # Main JS file
    main_js = """
    // Main application JavaScript
    document.addEventListener('DOMContentLoaded', function() {
        // Initialize tooltips
        const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'))
        const tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
            return new bootstrap.Tooltip(tooltipTriggerEl)
        });
        
        // Initialize popovers
        const popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'))
        const popoverList = popoverTriggerList.map(function (popoverTriggerEl) {
            return new bootstrap.Popover(popoverTriggerEl)
        });
        
        // Active navigation highlighting
        const currentPath = window.location.pathname;
        const navLinks = document.querySelectorAll('.nav-link');
        
        navLinks.forEach(link => {
            const linkPath = link.getAttribute('href');
            if (linkPath && currentPath.includes(linkPath) && linkPath !== '/') {
                link.classList.add('active');
            } else if (linkPath === '/' && currentPath === '/') {
                link.classList.add('active');
            }
        });
        
        // Handle flash messages auto-dismiss
        const flashMessages = document.querySelectorAll('.alert-dismissible');
        flashMessages.forEach(message => {
            setTimeout(() => {
                // Create a fadeout effect
                message.style.transition = 'opacity 1s';
                message.style.opacity = '0';
                
                // Remove after fadeout
                setTimeout(() => {
                    message.remove();
                }, 1000);
            }, 5000); // 5 seconds
        });
        
        // Password strength indicator
        const passwordInput = document.getElementById('password');
        const passwordStrength = document.getElementById('password-strength');
        
        if (passwordInput && passwordStrength) {
            passwordInput.addEventListener('input', function() {
                const strength = checkPasswordStrength(this.value);
                
                passwordStrength.className = 'password-strength';
                if (strength === 'weak') {
                    passwordStrength.classList.add('weak');
                    passwordStrength.textContent = 'Weak';
                } else if (strength === 'medium') {
                    passwordStrength.classList.add('medium');
                    passwordStrength.textContent = 'Medium';
                } else {
                    passwordStrength.classList.add('strong');
                    passwordStrength.textContent = 'Strong';
                }
            });
        }
    });
    
    // Password strength checker
    function checkPasswordStrength(password) {
        if (password.length < 6) {
            return 'weak';
        }
        
        let score = 0;
        
        // Has uppercase letter
        if (/[A-Z]/.test(password)) score++;
        
        // Has lowercase letter
        if (/[a-z]/.test(password)) score++;
        
        // Has number
        if (/[0-9]/.test(password)) score++;
        
        // Has special character
        if (/[^A-Za-z0-9]/.test(password)) score++;
        
        // Length > 10
        if (password.length > 10) score++;
        
        if (score >= 4) return 'strong';
        if (score >= 2) return 'medium';
        return 'weak';
    }
    
    // Handle sidebar toggle on mobile
    function toggleSidebar() {
        const sidebar = document.getElementById('sidebar');
        if (sidebar) {
            sidebar.classList.toggle('d-none');
        }
    }
    """
    
    with open('static/js/main.js', 'w') as f:
        f.write(main_js)

def generate_base_templates():
    """Generate the base HTML templates for the application"""
    os.makedirs('templates', exist_ok=True)
    
    # Base template with common layout
    base_html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{% block title %}{{ app_name }}{% endblock %}</title>
        
        <!-- Bootstrap CSS -->
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <!-- Font Awesome -->
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
        <!-- Custom CSS -->
        <link href="{{ url_for('static', filename='css/main.css') }}" rel="stylesheet">
        <link href="{{ url_for('static', filename='css/data_module.css') }}" rel="stylesheet">
        <link href="{{ url_for('static', filename='css/analysis_module.css') }}" rel="stylesheet">
        <link href="{{ url_for('static', filename='css/viz_module.css') }}" rel="stylesheet">
        
        {% block styles %}{% endblock %}
    </head>
    <body>
        <!-- Navigation -->
        <nav class="navbar navbar-expand-lg navbar-dark">
            <div class="container-fluid">
                <a class="navbar-brand" href="{{ url_for('web.index') }}">
                    <i class="fas fa-shield-alt me-2"></i>{{ app_name }}
                </a>
                <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
                    <span class="navbar-toggler-icon"></span>
                </button>
                <div class="collapse navbar-collapse" id="navbarNav">
                    <ul class="navbar-nav me-auto">
                        <li class="nav-item">
                            <a class="nav-link" href="{{ url_for('web.index') }}">
                                <i class="fas fa-home me-1"></i>Home
                            </a>
                        </li>
                        {% if current_user.is_authenticated %}
                        <li class="nav-item">
                            <a class="nav-link" href="{{ url_for('web.dashboard') }}">
                                <i class="fas fa-tachometer-alt me-1"></i>Dashboard
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="{{ url_for('data.index') }}">
                                <i class="fas fa-database me-1"></i>Data
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="{{ url_for('analysis.index') }}">
                                <i class="fas fa-search me-1"></i>Analysis
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="{{ url_for('viz.index') }}">
                                <i class="fas fa-chart-bar me-1"></i>Visualization
                            </a>
                        </li>
                        {% endif %}
                        <li class="nav-item">
                            <a class="nav-link" href="{{ url_for('web.about') }}">
                                <i class="fas fa-info-circle me-1"></i>About
                            </a>
                        </li>
                    </ul>
                    
                    <ul class="navbar-nav">
                        {% if current_user.is_authenticated %}
                        <li class="nav-item dropdown">
                            <a class="nav-link dropdown-toggle" href="#" id="userDropdown" role="button" data-bs-toggle="dropdown" aria-expanded="false">
                                <i class="fas fa-user-circle me-1"></i>{{ current_user.username }}
                                {% if current_user.role == 'admin' %}
                                <span class="user-badge">Admin</span>
                                {% endif %}
                            </a>
                            <ul class="dropdown-menu dropdown-menu-end" aria-labelledby="userDropdown">
                                <li><a class="dropdown-item" href="{{ url_for('web.profile') }}"><i class="fas fa-id-card me-2"></i>Profile</a></li>
                                {% if current_user.role == 'admin' %}
                                <li><a class="dropdown-item" href="{{ url_for('web.admin') }}"><i class="fas fa-users-cog me-2"></i>Admin</a></li>
                                {% endif %}
                                <li><hr class="dropdown-divider"></li>
                                <li><a class="dropdown-item" href="{{ url_for('web.logout') }}"><i class="fas fa-sign-out-alt me-2"></i>Logout</a></li>
                            </ul>
                        </li>
                        {% else %}
                        <li class="nav-item">
                            <a class="nav-link" href="{{ url_for('web.login') }}">
                                <i class="fas fa-sign-in-alt me-1"></i>Login
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="{{ url_for('web.register') }}">
                                <i class="fas fa-user-plus me-1"></i>Register
                            </a>
                        </li>
                        {% endif %}
                    </ul>
                </div>
            </div>
        </nav>
        
        <!-- Main Content -->
        <main class="main-content py-4">
            {% block content %}{% endblock %}
        </main>
        
        <!-- Footer -->
        <footer class="footer">
            <div class="container">
                <div class="row">
                    <div class="col-md-6">
                        <h5>{{ app_name }}</h5>
                        <p>A modern platform for security analysts to craft and test hunt hypotheses.</p>
                    </div>
                    <div class="col-md-3">
                        <h5>Navigation</h5>
                        <ul class="list-unstyled">
                            <li><a href="{{ url_for('web.index') }}" class="text-white">Home</a></li>
                            {% if current_user.is_authenticated %}
                            <li><a href="{{ url_for('data.index') }}" class="text-white">Data</a></li>
                            <li><a href="{{ url_for('analysis.index') }}" class="text-white">Analysis</a></li>
                            <li><a href="{{ url_for('viz.index') }}" class="text-white">Visualization</a></li>
                            {% endif %}
                        </ul>
                    </div>
                    <div class="col-md-3">
                        <h5>Resources</h5>
                        <ul class="list-unstyled">
                            <li><a href="{{ url_for('web.about') }}" class="text-white">About</a></li>
                            <li><a href="#" class="text-white">Documentation</a></li>
                            <li><a href="#" class="text-white">Support</a></li>
                        </ul>
                    </div>
                </div>
                <div class="row mt-3">
                    <div class="col-12 text-center">
                        <p class="mb-0">&copy; {{ year }} {{ app_name }}. All rights reserved.</p>
                    </div>
                </div>
            </div>
        </footer>
        
        <!-- Bootstrap JS Bundle with Popper -->
        <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
        <!-- Main JS -->
        <script src="{{ url_for('static', filename='js/main.js') }}"></script>
        
        {% block scripts %}{% endblock %}
    </body>
    </html>
    """
    
    # Login page template
    login_html = """
    {% extends 'base.html' %}
    
    {% block title %}Login - {{ app_name }}{% endblock %}
    
    {% block content %}
    <div class="container">
        <div class="card auth-card">
            <div class="card-body">
                <div class="auth-header">
                    <i class="fas fa-sign-in-alt"></i>
                    <h2>Login</h2>
                    <p class="text-muted">Enter your credentials to access your account</p>
                </div>
                
                {% with messages = get_flashed_messages(with_categories=true) %}
                  {% if messages %}
                    {% for category, message in messages %}
                      <div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">
                        {{ message }}
                        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                      </div>
                    {% endfor %}
                  {% endif %}
                {% endwith %}
                
                <form method="POST" action="{{ url_for('web.login') }}">
                    <div class="mb-3">
                        <label for="username" class="form-label">Username</label>
                        <div class="input-group">
                            <span class="input-group-text"><i class="fas fa-user"></i></span>
                            <input type="text" class="form-control" id="username" name="username" required>
                        </div>
                    </div>
                    
                    <div class="mb-3">
                        <label for="password" class="form-label">Password</label>
                        <div class="input-group">
                            <span class="input-group-text"><i class="fas fa-lock"></i></span>
                            <input type="password" class="form-control" id="password" name="password" required>
                        </div>
                    </div>
                    
                    <div class="mb-3 form-check">
                        <input type="checkbox" class="form-check-input" id="remember" name="remember">
                        <label class="form-check-label" for="remember">Remember me</label>
                    </div>
                    
                    <div class="d-grid">
                        <button type="submit" class="btn btn-primary">Login</button>
                    </div>
                </form>
                
                <div class="auth-footer">
                    <p>Don't have an account? <a href="{{ url_for('web.register') }}">Register</a></p>
                </div>
            </div>
        </div>
    </div>
    {% endblock %}
    """
    
    # Register page template
    register_html = """
    {% extends 'base.html' %}
    
    {% block title %}Register - {{ app_name }}{% endblock %}
    
    {% block content %}
    <div class="container">
        <div class="card auth-card">
            <div class="card-body">
                <div class="auth-header">
                    <i class="fas fa-user-plus"></i>
                    <h2>Create Account</h2>
                    <p class="text-muted">Join the {{ app_name }} platform</p>
                </div>
                
                {% with messages = get_flashed_messages(with_categories=true) %}
                  {% if messages %}
                    {% for category, message in messages %}
                      <div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">
                        {{ message }}
                        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
                      </div>
                    {% endfor %}
                  {% endif %}
                {% endwith %}
                
                <form method="POST" action="{{ url_for('web.register') }}">
                    <div class="mb-3">
                        <label for="username" class="form-label">Username</label>
                        <div class="input-group">
                            <span class="input-group-text"><i class="fas fa-user"></i></span>
                            <input type="text" class="form-control" id="username" name="username" required>
                        </div>
                    </div>
                    
                    <div class="mb-3">
                        <label for="email" class="form-label">Email</label>
                        <div class="input-group">
                            <span class="input-group-text"><i class="fas fa-envelope"></i></span>
                            <input type="email" class="form-control" id="email" name="email" required>
                        </div>
                    </div>
                    
                    <div class="mb-3">
                        <label for="password" class="form-label">Password</label>
                        <div class="input-group">
                            <span class="input-group-text"><i class="fas fa-lock"></i></span>
                            <input type="password" class="form-control" id="password" name="password" required>
                        </div>
                        <div id="password-strength" class="form-text"></div>
                    </div>
                    
                    <div class="mb-3">
                        <label for="password_confirm" class="form-label">Confirm Password</label>
                        <div class="input-group">
                            <span class="input-group-text"><i class="fas fa-lock"></i></span>
                            <input type="password" class="form-control" id="password_confirm" name="password_confirm" required>
                        </div>
                    </div>
                    
                    <div class="d-grid">
                        <button type="submit" class="btn btn-primary">Register</button>
                    </div>
                </form>
                
                <div class="auth-footer">
                    <p>Already have an account? <a href="{{ url_for('web.login') }}">Login</a></p>
                </div>
            </div>
        </div>
    </div>
    {% endblock %}
    
    {% block scripts %}
    <style>
        .password-strength {
            margin-top: 0.5rem;
            font-weight: bold;
        }
        .password-strength.weak { color: var(--danger-color); }
        .password-strength.medium { color: var(--warning-color); }
        .password-strength.strong { color: var(--success-color); }
    </style>
    {% endblock %}
    """
    
    # Profile page template
    profile_html = """
    {% extends 'base.html' %}
    
    {% block title %}My Profile - {{ app_name }}{% endblock %}
    
    {% block content %}
    <div class="profile-header">
        <div class="container text-center">
            <div class="profile-avatar">
                <i class="fas fa-user"></i>
            </div>
            <h2>{{ current_user.username }}</h2>
            <p class="lead">{{ current_user.email }}</p>
            <p>
                <span class="badge bg-info">{{ current_user.role|title }}</span>
            </p>
        </div>
    </div>
    
    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">
                {{ message }}
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
              </div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        
        <div class="row">
            <div class="col-md-6">
                <div class="card mb-4">
                    <div class="card-header">
                        <h4 class="mb-0">Account Information</h4>
                    </div>
                    <div class="card-body">
                        <form method="POST" action="#">
                            <div class="mb-3">
                                <label for="username" class="form-label">Username</label>
                                <input type="text" class="form-control" id="username" value="{{ current_user.username }}" readonly>
                            </div>
                            
                            <div class="mb-3">
                                <label for="email" class="form-label">Email</label>
                                <input type="email" class="form-control" id="email" value="{{ current_user.email }}">
                            </div>
                            
                            <button type="submit" class="btn btn-primary">Update Profile</button>
                        </form>
                    </div>
                </div>
            </div>
            
            <div class="col-md-6">
                <div class="card mb-4">
                    <div class="card-header">
                        <h4 class="mb-0">Change Password</h4>
                    </div>
                    <div class="card-body">
                        <form method="POST" action="#">
                            <div class="mb-3">
                                <label for="current_password" class="form-label">Current Password</label>
                                <input type="password" class="form-control" id="current_password" name="current_password" required>
                            </div>
                            
                            <div class="mb-3">
                                <label for="new_password" class="form-label">New Password</label>
                                <input type="password" class="form-control" id="new_password" name="new_password" required>
                            </div>
                            
                            <div class="mb-3">
                                <label for="confirm_password" class="form-label">Confirm New Password</label>
                                <input type="password" class="form-control" id="confirm_password" name="confirm_password" required>
                            </div>
                            
                            <button type="submit" class="btn btn-primary">Change Password</button>
                        </form>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="card mb-4">
            <div class="card-header">
                <h4 class="mb-0">Activity Summary</h4>
            </div>
            <div class="card-body">
                <div class="row text-center">
                    <div class="col-md-4">
                        <div class="p-3">
                            <i class="fas fa-database fa-2x mb-2 text-primary"></i>
                            <h4>5</h4>
                            <p class="text-muted">Datasets</p>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="p-3">
                            <i class="fas fa-search fa-2x mb-2 text-primary"></i>
                            <h4>12</h4>
                            <p class="text-muted">Analyses</p>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="p-3">
                            <i class="fas fa-chart-bar fa-2x mb-2 text-primary"></i>
                            <h4>8</h4>
                            <p class="text-muted">Visualizations</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    {% endblock %}
    """
    
    # Admin page template
    admin_html = """
    {% extends 'base.html' %}
    
    {% block title %}Admin Dashboard - {{ app_name }}{% endblock %}
    
    {% block content %}
    <div class="container">
        <h1 class="mb-4">Admin Dashboard</h1>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">
                {{ message }}
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
              </div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        
        <div class="row mb-4">
            <div class="col-md-3">
                <div class="card text-center p-3">
                    <div class="p-3 mb-2">
                        <i class="fas fa-users fa-3x text-primary"></i>
                    </div>
                    <h4>{{ users|length }}</h4>
                    <p class="text-muted">Total Users</p>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card text-center p-3">
                    <div class="p-3 mb-2">
                        <i class="fas fa-database fa-3x text-primary"></i>
                    </div>
                    <h4>10</h4>
                    <p class="text-muted">Total Datasets</p>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card text-center p-3">
                    <div class="p-3 mb-2">
                        <i class="fas fa-search fa-3x text-primary"></i>
                    </div>
                    <h4>25</h4>
                    <p class="text-muted">Total Analyses</p>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card text-center p-3">
                    <div class="p-3 mb-2">
                        <i class="fas fa-chart-bar fa-3x text-primary"></i>
                    </div>
                    <h4>18</h4>
                    <p class="text-muted">Total Visualizations</p>
                </div>
            </div>
        </div>
        
        <div class="card mb-4">
            <div class="card-header d-flex justify-content-between align-items-center">
                <h4 class="mb-0">User Management</h4>
                <button class="btn btn-primary btn-sm">
                    <i class="fas fa-user-plus"></i> Add User
                </button>
            </div>
            <div class="card-body">
                <div class="table-responsive">
                    <table class="table table-hover">
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>Username</th>
                                <th>Email</th>
                                <th>Role</th>
                                <th>Created</th>
                                <th>Last Login</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for user in users %}
                            <tr>
                                <td>{{ user.id }}</td>
                                <td>{{ user.username }}</td>
                                <td>{{ user.email }}</td>
                                <td>
                                    <span class="badge bg-{{ 'danger' if user.role == 'admin' else 'primary' }}">
                                        {{ user.role }}
                                    </span>
                                </td>
                                <td>{{ user.created_at|format_date }}</td>
                                <td>{{ user.last_login|format_date if user.last_login else 'Never' }}</td>
                                <td>
                                    <div class="btn-group btn-group-sm">
                                        <button class="btn btn-outline-primary"><i class="fas fa-edit"></i></button>
                                        <button class="btn btn-outline-danger"><i class="fas fa-trash"></i></button>
                                    </div>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
        
        <div class="row">
            <div class="col-md-6">
                <div class="card mb-4">
                    <div class="card-header">
                        <h4 class="mb-0">System Settings</h4>
                    </div>
                    <div class="card-body">
                        <form method="POST" action="#">
                            <div class="mb-3">
                                <label for="app_name" class="form-label">Application Name</label>
                                <input type="text" class="form-control" id="app_name" value="{{ app_name }}">
                            </div>
                            
                            <div class="mb-3">
                                <label for="primary_color" class="form-label">Primary Color</label>
                                <input type="color" class="form-control form-control-color" id="primary_color" value="{{ colors.primary }}">
                            </div>
                            
                            <div class="mb-3 form-check">
                                <input type="checkbox" class="form-check-input" id="enable_registration" checked>
                                <label class="form-check-label" for="enable_registration">Enable User Registration</label>
                            </div>
                            
                            <button type="submit" class="btn btn-primary">Save Settings</button>
                        </form>
                    </div>
                </div>
            </div>
            <div class="col-md-6">
                <div class="card mb-4">
                    <div class="card-header">
                        <h4 class="mb-0">System Information</h4>
                    </div>
                    <div class="card-body">
                        <dl class="row">
                            <dt class="col-sm-5">Application Version:</dt>
                            <dd class="col-sm-7">1.0.0</dd>
                            
                            <dt class="col-sm-5">Flask Version:</dt>
                            <dd class="col-sm-7">2.3.3</dd>
                            
                            <dt class="col-sm-5">Python Version:</dt>
                            <dd class="col-sm-7">3.11.4</dd>
                            
                            <dt class="col-sm-5">Database:</dt>
                            <dd class="col-sm-7">SQLite 3</dd>
                            
                            <dt class="col-sm-5">Operating System:</dt>
                            <dd class="col-sm-7">Linux</dd>
                            
                            <dt class="col-sm-5">Server Time:</dt>
                            <dd class="col-sm-7">{{ now|format_datetime }}</dd>
                        </dl>
                    </div>
                </div>
            </div>
        </div>
    </div>
    {% endblock %}
    """
    
    # Write the templates to files
    templates = {
        'base.html': base_html,
        'login.html': login_html,
        'register.html': register_html,
        'profile.html': profile_html,
        'admin.html': admin_html,
    }
    
    for file_name, content in templates.items():
        with open(f'templates/{file_name}', 'w') as f:
            f.write(content)
