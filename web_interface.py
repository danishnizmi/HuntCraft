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
            'app_name': current_app.config.get('APP_NAME', 'Malware Detonation Platform'),
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

    # Ensure templates exist
    if app.config.get('GENERATE_TEMPLATES', False):
        generate_base_templates()

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
    conn = sqlite3.connect(current_app.config.get('DATABASE_PATH', '/app/data/malware_platform.db'))
    if row_factory:
        conn.row_factory = row_factory
    return conn

# User functions
def get_user_by_id(user_id):
    """Get a user by ID"""
    try:
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
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error getting user: {e}")
    return None

def get_user_by_username(username):
    """Get a user by username"""
    try:
        conn = _db_connection(sqlite3.Row)
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        user_data = cursor.fetchone()
        
        conn.close()
        
        return dict(user_data) if user_data else None
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error getting user by username: {e}")
        return None

def validate_login(username, password):
    """Validate user login credentials"""
    user_data = get_user_by_username(username)
    if not user_data:
        return None
    
    try:
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
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error validating login: {e}")
    
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
    """Dashboard page - simplified to prevent memory issues"""
    return render_template('dashboard.html', 
                          datasets=[],
                          analyses=[],
                          visualizations=[])

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

@web_bp.route('/health')
def health():
    """Health check endpoint for Render"""
    import resource
    memory_usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # Convert to MB
    return {
        'status': 'ok', 
        'timestamp': datetime.now().isoformat(),
        'memory_usage_mb': memory_usage
    }

# Error handlers
def handle_404():
    """Handle 404 errors"""
    return "Page not found", 404

def handle_500():
    """Handle 500 errors"""
    return "Server error", 500

# Template generation
def generate_base_templates():
    """Generate essential HTML templates for the application"""
    import logging
    logger = logging.getLogger(__name__)
    
    os.makedirs('templates', exist_ok=True)
    
    # Create a simple index.html template if it doesn't exist
    if not os.path.exists('templates/index.html'):
        with open('templates/index.html', 'w') as f:
            f.write("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ app_name }}</title>
    <style>
        body {
            font-family: 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            text-align: center;
        }
        h1 { color: #4a6fa5; }
        .card {
            background: #f8f9fa;
            border-radius: 8px;
            padding: 20px;
            margin-top: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .nav {
            margin: 20px 0;
            padding: 0;
            list-style: none;
        }
        .nav li {
            display: inline-block;
            margin: 0 10px;
        }
        .nav a {
            color: #4a6fa5;
            text-decoration: none;
            padding: 5px 10px;
            border-radius: 4px;
        }
        .nav a:hover {
            background: #e9ecef;
        }
    </style>
</head>
<body>
    <h1>{{ app_name }}</h1>
    
    <ul class="nav">
        <li><a href="/">Home</a></li>
        {% if current_user.is_authenticated %}
        <li><a href="/dashboard">Dashboard</a></li>
        <li><a href="/malware">Malware</a></li>
        <li><a href="/detonation">Detonation</a></li>
        <li><a href="/viz">Visualizations</a></li>
        <li><a href="/logout">Logout</a></li>
        {% else %}
        <li><a href="/login">Login</a></li>
        {% endif %}
    </ul>
    
    <div class="card">
        <h2>Welcome to the Malware Analysis Platform</h2>
        <p>Use the navigation above to access different features of the platform.</p>
    </div>
    
    <script>
        // Check server health periodically
        function checkHealth() {
            fetch('/health')
                .then(response => response.json())
                .catch(error => console.error('Error checking health:', error));
        }
        
        // Check every 30 seconds
        setInterval(checkHealth, 30000);
    </script>
</body>
</html>""")
        logger.info("Created index.html template")

    # Create a basic login template if it doesn't exist
    if not os.path.exists('templates/login.html'):
        with open('templates/login.html', 'w') as f:
            f.write("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - {{ app_name }}</title>
    <style>
        body {
            font-family: 'Helvetica Neue', Arial, sans-serif;
            margin: 40px;
            text-align: center;
            color: #333;
        }
        .login-form {
            max-width: 400px;
            margin: 0 auto;
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        input {
            width: 100%;
            padding: 10px;
            margin: 10px 0;
            border: 1px solid #ddd;
            border-radius: 4px;
        }
        button {
            background: #4a6fa5;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 4px;
            cursor: pointer;
        }
        .alert {
            padding: 10px;
            margin: 20px 0;
            border-radius: 4px;
        }
        .alert-danger {
            background-color: #f8d7da;
            color: #721c24;
        }
        .alert-success {
            background-color: #d4edda;
            color: #155724;
        }
    </style>
</head>
<body>
    <div class="login-form">
        <h1>{{ app_name }}</h1>
        <h2>Login</h2>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="alert alert-{{ category }}">{{ message }}</div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        
        <form method="POST">
            <div>
                <input type="text" name="username" placeholder="Username" required>
            </div>
            <div>
                <input type="password" name="password" placeholder="Password" required>
            </div>
            <div>
                <button type="submit">Login</button>
            </div>
            
            <p><small>Default: admin / admin123</small></p>
        </form>
    </div>
</body>
</html>""")
        logger.info("Created login.html template")

    # Create a basic dashboard template if it doesn't exist
    if not os.path.exists('templates/dashboard.html'):
        with open('templates/dashboard.html', 'w') as f:
            f.write("""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard - {{ app_name }}</title>
    <style>
        body {
            font-family: 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        h1, h2, h3 { color: #4a6fa5; }
        .card {
            background: #f8f9fa;
            border-radius: 8px;
            padding: 20px;
            margin-top: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .nav {
            margin: 20px 0;
            padding: 0;
            list-style: none;
        }
        .nav li {
            display: inline-block;
            margin: 0 10px;
        }
        .nav a {
            color: #4a6fa5;
            text-decoration: none;
            padding: 5px 10px;
            border-radius: 4px;
        }
        .nav a:hover {
            background: #e9ecef;
        }
        .dashboard-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 20px;
        }
    </style>
</head>
<body>
    <h1>Dashboard</h1>
    
    <ul class="nav">
        <li><a href="/">Home</a></li>
        <li><a href="/dashboard">Dashboard</a></li>
        <li><a href="/malware">Malware</a></li>
        <li><a href="/detonation">Detonation</a></li>
        <li><a href="/viz">Visualizations</a></li>
        <li><a href="/logout">Logout</a></li>
    </ul>
    
    <div class="card">
        <h2>Welcome, {{ current_user.username }}</h2>
        <p>This is a simplified dashboard to reduce memory usage.</p>
    </div>
    
    <div class="dashboard-grid">
        <div class="card">
            <h3>Recent Malware Samples</h3>
            {% if datasets %}
                <ul>
                {% for dataset in datasets %}
                    <li><a href="/malware/view/{{ dataset.id }}">{{ dataset.name }}</a></li>
                {% endfor %}
                </ul>
            {% else %}
                <p>No recent samples.</p>
            {% endif %}
        </div>
        
        <div class="card">
            <h3>Recent Analyses</h3>
            {% if analyses %}
                <ul>
                {% for analysis in analyses %}
                    <li><a href="/detonation/view/{{ analysis.id }}">{{ analysis.name }}</a></li>
                {% endfor %}
                </ul>
            {% else %}
                <p>No recent analyses.</p>
            {% endif %}
        </div>
    </div>
</body>
</html>""")
        logger.info("Created dashboard.html template")
    
    # Create a minimal base CSS file
    os.makedirs('static/css', exist_ok=True)
    if not os.path.exists('static/css/main.css'):
        with open('static/css/main.css', 'w') as f:
            f.write("""
/* Minimal CSS for the application */
body {
    font-family: 'Helvetica Neue', Arial, sans-serif;
    line-height: 1.6;
    color: #333;
}
.container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 20px;
}
h1, h2, h3 { color: #4a6fa5; }
.card {
    background: #f8f9fa;
    border-radius: 8px;
    padding: 20px;
    margin-top: 20px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}
""")
        logger.info("Created basic CSS file")
