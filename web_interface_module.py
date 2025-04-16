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
        # Try getting datasets from malware_module (new) or data_module (old)
        try:
            from malware_module import get_datasets
            all_datasets = get_datasets()
            user_datasets = all_datasets[:3]  # Just showing 3 most recent for demo
        except ImportError:
            try:
                from data_module import get_datasets
                all_datasets = get_datasets()
                user_datasets = all_datasets[:3]
            except ImportError:
                # If neither module is available
                user_datasets = []
        
        # Try getting analyses from detonation_module (new) or analysis_module (old)
        try:
            from detonation_module import get_saved_queries
            all_queries = get_saved_queries()
            user_analyses = all_queries[:3]
        except (ImportError, AttributeError):
            try:
                from analysis_module import get_saved_queries
                all_queries = get_saved_queries()
                user_analyses = all_queries[:3]
            except (ImportError, AttributeError):
                # If neither module is available or function doesn't exist
                user_analyses = []
        
        # Get user's visualizations
        try:
            from viz_module import get_visualizations
            all_visualizations = get_visualizations()
            user_visualizations = all_visualizations[:3]
        except (ImportError, AttributeError):
            # If viz_module is not available or function doesn't exist
            user_visualizations = []
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
    return render_template('404.html') if os.path.exists('templates/404.html') else "Page not found", 404

def handle_500():
    """Handle 500 errors"""
    return render_template('500.html') if os.path.exists('templates/500.html') else "Server error", 500

# Static file generators
def generate_css():
    """Generate CSS for the web interface"""
    os.makedirs('static/css', exist_ok=True)
    
    # Main CSS file
    main_css = """
    /* Main application styling */
    :root {
        --primary-color: """ + current_app.config.get('PRIMARY_COLOR', '#4a6fa5') + """;
        --secondary-color: """ + current_app.config.get('SECONDARY_COLOR', '#6c757d') + """;
        --danger-color: """ + current_app.config.get('DANGER_COLOR', '#dc3545') + """;
        --success-color: """ + current_app.config.get('SUCCESS_COLOR', '#28a745') + """;
        --warning-color: """ + current_app.config.get('WARNING_COLOR', '#ffc107') + """;
        --info-color: """ + current_app.config.get('INFO_COLOR', '#17a2b8') + """;
        --dark-color: """ + current_app.config.get('DARK_COLOR', '#343a40') + """;
        --light-color: """ + current_app.config.get('LIGHT_COLOR', '#f8f9fa') + """;
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
    
    # Create a simple index.html template if it doesn't exist
    if not os.path.exists('templates/index.html'):
        index_html = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Malware Detonation Platform</title>
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        </head>
        <body>
            <div class="container mt-5">
                <div class="text-center">
                    <h1>Malware Detonation Platform</h1>
                    <p class="lead">A platform for security analysts to analyze and detonate malware samples.</p>
                    <div class="mt-4">
                        <a href="/login" class="btn btn-primary">Login</a>
                        <a href="/register" class="btn btn-outline-primary">Register</a>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """
        with open('templates/index.html', 'w') as f:
            f.write(index_html)
