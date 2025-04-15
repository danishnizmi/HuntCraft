from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
import os
import json
from datetime import datetime

# Create blueprint
web_bp = Blueprint('web', __name__, url_prefix='')

def init_app(app):
    """Initialize the web interface module with the Flask app"""
    app.register_blueprint(web_bp)
    
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
            'year': datetime.now().year
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

# Basic routes
@web_bp.route('/')
def index():
    """Home page"""
    return render_template('index.html')

@web_bp.route('/dashboard')
def dashboard():
    """Dashboard page"""
    return render_template('dashboard.html')

@web_bp.route('/about')
def about():
    """About page"""
    return render_template('about.html')

@web_bp.route('/health')
def health():
    """Health check endpoint for Render"""
    return {'status': 'ok', 'timestamp': datetime.now().isoformat()}

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
    });
    
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
        <link href="{{ url_for('static', filename='css/visualization_module.css') }}" rel="stylesheet">
        
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
                            <a class="nav-link" href="{{ url_for('visualization.index') }}">
                                <i class="fas fa-chart-bar me-1"></i>Visualization
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="{{ url_for('web.about') }}">
                                <i class="fas fa-info-circle me-1"></i>About
                            </a>
                        </li>
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
                            <li><a href="{{ url_for('data.index') }}" class="text-white">Data</a></li>
                            <li><a href="{{ url_for('analysis.index') }}" class="text-white">Analysis</a></li>
                            <li><a href="{{ url_for('visualization.index') }}" class="text-white">Visualization</a></li>
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
    
    # Index/home page template
    index_html = """
    {% extends 'base.html' %}
    
    {% block title %}Home - {{ app_name }}{% endblock %}
    
    {% block content %}
    <div class="container">
        <div class="row align-items-center mb-5">
            <div class="col-md-6">
                <h1 class="display-4 fw-bold">Welcome to {{ app_name }}</h1>
                <p class="lead">A comprehensive platform for security analysts to craft and test hunt hypotheses against sample datasets.</p>
                <div class="d-grid gap-2 d-md-flex justify-content-md-start mt-4">
                    <a href="{{ url_for('data.upload') }}" class="btn btn-primary btn-lg px-4 me-md-2">
                        <i class="fas fa-upload me-2"></i>Upload Data
                    </a>
                    <a href="{{ url_for('web.dashboard') }}" class="btn btn-outline-secondary btn-lg px-4">
                        <i class="fas fa-tachometer-alt me-2"></i>Dashboard
                    </a>
                </div>
            </div>
            <div class="col-md-6 text-center">
                <i class="fas fa-shield-alt" style="font-size: 10rem; color: var(--primary-color); opacity: 0.8;"></i>
            </div>
        </div>
        
        <hr class="my-5">
        
        <div class="row mb-5">
            <div class="col-12 text-center mb-4">
                <h2>Key Features</h2>
                <p class="lead">Discover the powerful tools at your disposal</p>
            </div>
            
            <div class="col-md-4 mb-4">
                <div class="card h-100">
                    <div class="card-body text-center">
                        <i class="fas fa-database mb-3" style="font-size: 3rem; color: var(--primary-color);"></i>
                        <h3 class="card-title">Data Management</h3>
                        <p class="card-text">Upload, preprocess, and manage various dataset formats including CSV, JSON, and Excel files.</p>
                        <a href="{{ url_for('data.index') }}" class="btn btn-outline-primary">Explore Data</a>
                    </div>
                </div>
            </div>
            
            <div class="col-md-4 mb-4">
                <div class="card h-100">
                    <div class="card-body text-center">
                        <i class="fas fa-search mb-3" style="font-size: 3rem; color: var(--primary-color);"></i>
                        <h3 class="card-title">Analysis Tools</h3>
                        <p class="card-text">Create custom queries, analyze patterns, and develop hunt hypotheses for threat detection.</p>
                        <a href="{{ url_for('analysis.index') }}" class="btn btn-outline-primary">Start Analysis</a>
                    </div>
                </div>
            </div>
            
            <div class="col-md-4 mb-4">
                <div class="card h-100">
                    <div class="card-body text-center">
                        <i class="fas fa-chart-bar mb-3" style="font-size: 3rem; color: var(--primary-color);"></i>
                        <h3 class="card-title">Visualization</h3>
                        <p class="card-text">Transform data into insightful visualizations and reports to identify threats and anomalies.</p>
                        <a href="{{ url_for('visualization.index') }}" class="btn btn-outline-primary">View Visualizations</a>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="row mt-5">
            <div class="col-12 text-center">
                <h2>Get Started Today</h2>
                <p class="lead">Begin your threat hunting journey with these simple steps</p>
            </div>
            
            <div class="col-md-3 text-center mt-4">
                <div class="p-3">
                    <div class="bg-primary rounded-circle d-inline-flex justify-content-center align-items-center" style="width: 60px; height: 60px;">
                        <span class="text-white fw-bold">1</span>
                    </div>
                    <h4 class="mt-3">Upload Data</h4>
                    <p>Import your security datasets in various formats</p>
                </div>
            </div>
            
            <div class="col-md-3 text-center mt-4">
                <div class="p-3">
                    <div class="bg-primary rounded-circle d-inline-flex justify-content-center align-items-center" style="width: 60px; height: 60px;">
                        <span class="text-white fw-bold">2</span>
                    </div>
                    <h4 class="mt-3">Create Analysis</h4>
                    <p>Develop queries and analysis rules</p>
                </div>
            </div>
            
            <div class="col-md-3 text-center mt-4">
                <div class="p-3">
                    <div class="bg-primary rounded-circle d-inline-flex justify-content-center align-items-center" style="width: 60px; height: 60px;">
                        <span class="text-white fw-bold">3</span>
                    </div>
                    <h4 class="mt-3">Visualize Results</h4>
                    <p>Generate insightful charts and graphs</p>
                </div>
            </div>
            
            <div class="col-md-3 text-center mt-4">
                <div class="p-3">
                    <div class="bg-primary rounded-circle d-inline-flex justify-content-center align-items-center" style="width: 60px; height: 60px;">
                        <span class="text-white fw-bold">4</span>
                    </div>
                    <h4 class="mt-3">Export Findings</h4>
                    <p>Share and export your threat hunting results</p>
                </div>
            </div>
        </div>
    </div>
    {% endblock %}
    """
    
    # Dashboard template
    dashboard_html = """
    {% extends 'base.html' %}
    
    {% block title %}Dashboard - {{ app_name }}{% endblock %}
    
    {% block content %}
    <div class="container">
        <h1 class="mb-4">Dashboard</h1>
        
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
                <div class="card stats-card">
                    <div class="stats-icon">
                        <i class="fas fa-database"></i>
                    </div>
                    <div class="stats-number" id="dataset-count">-</div>
                    <div class="stats-title">Datasets</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card stats-card">
                    <div class="stats-icon">
                        <i class="fas fa-search"></i>
                    </div>
                    <div class="stats-number" id="analysis-count">-</div>
                    <div class="stats-title">Analyses</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card stats-card">
                    <div class="stats-icon">
                        <i class="fas fa-chart-bar"></i>
                    </div>
                    <div class="stats-number" id="visualization-count">-</div>
                    <div class="stats-title">Visualizations</div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card stats-card">
                    <div class="stats-icon">
                        <i class="fas fa-exclamation-triangle"></i>
                    </div>
                    <div class="stats-number" id="alert-count">-</div>
                    <div class="stats-title">Alerts</div>
                </div>
            </div>
        </div>
        
        <div class="row">
            <div class="col-md-6">
                <div class="card mb-4">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h5 class="mb-0">Recent Activity</h5>
                        <a href="#" class="btn btn-sm btn-outline-primary">View All</a>
                    </div>
                    <div class="card-body">
                        <div class="list-group list-group-flush" id="recent-activity">
                            <div class="list-group-item d-flex justify-content-between align-items-center">
                                <div>
                                    <div class="fw-bold">Data Upload</div>
                                    <div class="small text-muted">Windows Event Logs dataset uploaded</div>
                                </div>
                                <span class="badge bg-primary rounded-pill">3m ago</span>
                            </div>
                            <div class="list-group-item d-flex justify-content-between align-items-center">
                                <div>
                                    <div class="fw-bold">Analysis Created</div>
                                    <div class="small text-muted">Suspicious Process Analysis created</div>
                                </div>
                                <span class="badge bg-primary rounded-pill">15m ago</span>
                            </div>
                            <div class="list-group-item d-flex justify-content-between align-items-center">
                                <div>
                                    <div class="fw-bold">Visualization Generated</div>
                                    <div class="small text-muted">Network Traffic Timeline created</div>
                                </div>
                                <span class="badge bg-primary rounded-pill">1h ago</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="col-md-6">
                <div class="card mb-4">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h5 class="mb-0">Recent Datasets</h5>
                        <a href="{{ url_for('data.index') }}" class="btn btn-sm btn-outline-primary">View All</a>
                    </div>
                    <div class="card-body">
                        <div class="list-group list-group-flush" id="recent-datasets">
                            <!-- Datasets will be loaded via API -->
                            <div class="text-center py-3">
                                <div class="spinner-border text-primary" role="status">
                                    <span class="visually-hidden">Loading...</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="row">
            <div class="col-md-12">
                <div class="card mb-4">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h5 class="mb-0">Quick Actions</h5>
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-3 mb-3">
                                <a href="{{ url_for('data.upload') }}" class="btn btn-outline-primary w-100 p-3">
                                    <i class="fas fa-upload mb-2" style="font-size: 2rem;"></i>
                                    <div>Upload Data</div>
                                </a>
                            </div>
                            <div class="col-md-3 mb-3">
                                <a href="{{ url_for('analysis.create') }}" class="btn btn-outline-primary w-100 p-3">
                                    <i class="fas fa-search mb-2" style="font-size: 2rem;"></i>
                                    <div>New Analysis</div>
                                </a>
                            </div>
                            <div class="col-md-3 mb-3">
                                <a href="{{ url_for('visualization.create') }}" class="btn btn-outline-primary w-100 p-3">
                                    <i class="fas fa-chart-line mb-2" style="font-size: 2rem;"></i>
                                    <div>New Visualization</div>
                                </a>
                            </div>
                            <div class="col-md-3 mb-3">
                                <a href="#" class="btn btn-outline-primary w-100 p-3">
                                    <i class="fas fa-file-export mb-2" style="font-size: 2rem;"></i>
                                    <div>Export Report</div>
                                </a>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    {% endblock %}
    
    {% block scripts %}
    <script>
        document.addEventListener('DOMContentLoaded', function() {
            // Load dataset stats
            fetch('/data/api/datasets')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('dataset-count').textContent = data.length;
                    
                    // Update recent datasets
                    const recentDatasetsElement = document.getElementById('recent-datasets');
                    recentDatasetsElement.innerHTML = '';
                    
                    if (data.length === 0) {
                        recentDatasetsElement.innerHTML = '<div class="text-center py-3">No datasets found</div>';
                    } else {
                        // Show the most recent 3 datasets
                        data.slice(0, 3).forEach(dataset => {
                            const item = document.createElement('div');
                            item.className = 'list-group-item d-flex justify-content-between align-items-center';
                            item.innerHTML = `
                                <div>
                                    <div class="fw-bold">${dataset.name}</div>
                                    <div class="small text-muted">${dataset.row_count} records, ${dataset.source_type} format</div>
                                </div>
                                <a href="/data/view/${dataset.id}" class="btn btn-sm btn-outline-primary">View</a>
                            `;
                            recentDatasetsElement.appendChild(item);
                        });
                    }
                })
                .catch(error => {
                    console.error('Error fetching datasets:', error);
                    document.getElementById('recent-datasets').innerHTML = 
                        '<div class="text-center py-3">Error loading datasets</div>';
                });
            
            // Placeholder values for other stats - would be replaced with actual API calls
            document.getElementById('analysis-count').textContent = '3';
            document.getElementById('visualization-count').textContent = '5';
            document.getElementById('alert-count').textContent = '2';
        });
    </script>
    {% endblock %}
    """
    
    # About page template
    about_html = """
    {% extends 'base.html' %}
    
    {% block title %}About - {{ app_name }}{% endblock %}
    
    {% block content %}
    <div class="container">
        <div class="row">
            <div class="col-lg-8 offset-lg-2">
                <h1 class="mb-4">About {{ app_name }}</h1>
                
                <div class="card mb-4">
                    <div class="card-body">
                        <h2>Overview</h2>
                        <p>
                            {{ app_name }} is a comprehensive platform designed for security analysts to craft and test hunt 
                            hypotheses against various datasets. This tool simplifies the process of identifying threats and 
                            anomalies in security data through advanced analysis and visualization techniques.
                        </p>
                        
                        <h2 class="mt-4">Key Features</h2>
                        <ul>
                            <li>
                                <strong>Data Management:</strong> Upload, preprocess, and manage various dataset formats 
                                including CSV, JSON, and Excel files.
                            </li>
                            <li>
                                <strong>Advanced Analysis:</strong> Create custom queries, analyze patterns, and develop 
                                hunt hypotheses for threat detection.
                            </li>
                            <li>
                                <strong>Visualization:</strong> Transform data into insightful visualizations and reports 
                                to identify threats and anomalies.
                            </li>
                            <li>
                                <strong>Export Capabilities:</strong> Share and export your threat hunting results in 
                                various formats.
                            </li>
                        </ul>
                        
                        <h2 class="mt-4">Technology Stack</h2>
                        <p>
                            {{ app_name }} is built using a modern technology stack:
                        </p>
                        <ul>
                            <li><strong>Backend:</strong> Python with Flask framework</li>
                            <li><strong>Data Processing:</strong> Pandas and NumPy for efficient data manipulation</li>
                            <li><strong>Analysis:</strong> Scikit-learn for machine learning and pattern detection</li>
                            <li><strong>Visualization:</strong> Plotly for interactive data visualization</li>
                            <li><strong>Database:</strong> SQLite for data storage</li>
                            <li><strong>Frontend:</strong> Bootstrap for responsive design</li>
                        </ul>
                        
                        <h2 class="mt-4">Getting Started</h2>
                        <p>
                            To get started with {{ app_name }}, follow these simple steps:
                        </p>
                        <ol>
                            <li>Upload your security dataset via the <a href="{{ url_for('data.upload') }}">Data Upload</a> page.</li>
                            <li>Create a new analysis to explore the data and develop hunt hypotheses.</li>
                            <li>Generate visualizations to better understand patterns and anomalies.</li>
                            <li>Export your findings for reporting or further investigation.</li>
                        </ol>
                    </div>
                </div>
                
                <div class="card">
                    <div class="card-body">
                        <h2>Contact</h2>
                        <p>
                            For questions, feedback, or support requests, please contact us at:
                        </p>
                        <p>
                            <i class="fas fa-envelope me-2"></i> support@threathuntingworkbench.com<br>
                            <i class="fas fa-globe me-2"></i> www.threathuntingworkbench.com
                        </p>
                    </div>
                </div>
            </div>
        </div>
    </div>
    {% endblock %}
    """
    
    # 404 error page template
    error_404_html = """
    {% extends 'base.html' %}
    
    {% block title %}Page Not Found - {{ app_name }}{% endblock %}
    
    {% block content %}
    <div class="container text-center py-5">
        <div class="display-1 text-primary mb-3">
            <i class="fas fa-exclamation-circle"></i> 404
        </div>
        <h1 class="mb-4">Page Not Found</h1>
        <p class="lead mb-5">Sorry, we couldn't find the page you're looking for.</p>
        <div class="d-flex justify-content-center">
            <a href="{{ url_for('web.index') }}" class="btn btn-primary me-3">
                <i class="fas fa-home me-2"></i>Go to Home
            </a>
            <a href="javascript:history.back()" class="btn btn-outline-secondary">
                <i class="fas fa-arrow-left me-2"></i>Go Back
            </a>
        </div>
    </div>
    {% endblock %}
    """
    
    # 500 error page template
    error_500_html = """
    {% extends 'base.html' %}
    
    {% block title %}Server Error - {{ app_name }}{% endblock %}
    
    {% block content %}
    <div class="container text-center py-5">
        <div class="display-1 text-danger mb-3">
            <i class="fas fa-exclamation-triangle"></i> 500
        </div>
        <h1 class="mb-4">Server Error</h1>
        <p class="lead mb-5">Sorry, something went wrong on our end. Please try again later.</p>
        <div class="d-flex justify-content-center">
            <a href="{{ url_for('web.index') }}" class="btn btn-primary me-3">
                <i class="fas fa-home me-2"></i>Go to Home
            </a>
            <a href="javascript:history.back()" class="btn btn-outline-secondary">
                <i class="fas fa-arrow-left me-2"></i>Go Back
            </a>
        </div>
    </div>
    {% endblock %}
    """
    
    # Write the templates to files
    with open('templates/base.html', 'w') as f:
        f.write(base_html)
        
    with open('templates/index.html', 'w') as f:
        f.write(index_html)
        
    with open('templates/dashboard.html', 'w') as f:
        f.write(dashboard_html)
        
    with open('templates/about.html', 'w') as f:
        f.write(about_html)
        
    with open('templates/404.html', 'w') as f:
        f.write(error_404_html)
        
    with open('templates/500.html', 'w') as f:
        f.write(error_500_html)
