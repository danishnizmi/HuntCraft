from flask import Blueprint, request, render_template, current_app, jsonify, flash, redirect, url_for
import os
import json
import sqlite3
from datetime import datetime
import logging

# Try to import visualization dependencies
try:
    import pandas as pd
    import numpy as np
    import plotly
    import plotly.express as px
    import plotly.graph_objects as go
    VISUALIZATION_ENABLED = True
except ImportError:
    VISUALIZATION_ENABLED = False
    logging.getLogger(__name__).warning("Visualization dependencies not available. Install pandas, numpy, and plotly for full functionality.")

# Create blueprint with shorter name
viz_bp = Blueprint('viz', __name__, url_prefix='/viz')

def init_app(app):
    """Initialize the visualization module with the Flask app"""
    app.register_blueprint(viz_bp)
    
    # Only generate templates if explicitly configured to do so
    if app.config.get('GENERATE_TEMPLATES', False):
        generate_css()
        generate_js()
        generate_templates()

# Database schema related functions
def create_database_schema(cursor):
    """Create the necessary database tables for the visualization module"""
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS visualizations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        type TEXT NOT NULL,
        result_id INTEGER,
        config TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (result_id) REFERENCES analysis_results(id)
    )
    ''')

# Helper function for DB connections
def _db_connection(row_factory=None):
    """Create a database connection with optional row factory"""
    conn = sqlite3.connect(current_app.config['DATABASE_PATH'])
    if row_factory:
        conn.row_factory = row_factory
    return conn

# Routes
@viz_bp.route('/')
def index():
    """Visualization module main page"""
    if not VISUALIZATION_ENABLED:
        flash('Visualization is disabled due to missing dependencies. Please install pandas, numpy, and plotly.', 'warning')
        return render_template('visualization_disabled.html')
    
    visualizations = get_visualizations()
    return render_template('visualization_index.html', visualizations=visualizations)

@viz_bp.route('/create', methods=['GET', 'POST'])
def create():
    """Create visualization form and handler"""
    if not VISUALIZATION_ENABLED:
        flash('Visualization is disabled due to missing dependencies. Please install pandas, numpy, and plotly.', 'warning')
        return redirect(url_for('viz.index'))
        
    # Check if we're creating from an analysis result
    result_id = request.args.get('result_id', type=int)
    
    if not result_id:
        # No result specified, show available results
        try:
            # Use lazy loading for analysis module
            from main import get_module
            analysis_module = get_module('analysis')
            if analysis_module and hasattr(analysis_module, 'get_recent_results'):
                recent_results = analysis_module.get_recent_results(limit=10)
            else:
                recent_results = []
        except ImportError:
            recent_results = []
            
        return render_template('visualization_select_data.html', recent_results=recent_results)
    
    # Load result data - using lazy loading
    try:
        from main import get_module
        analysis_module = get_module('analysis')
        if analysis_module:
            result = analysis_module.get_result_by_id(result_id)
            query = analysis_module.get_query_by_id(result['query_id']) if result else None
        else:
            flash('Analysis module not available', 'error')
            return redirect(url_for('viz.index'))
    except ImportError:
        flash('Analysis module not available', 'error')
        return redirect(url_for('viz.index'))
    
    if not result:
        flash('Analysis result not found', 'error')
        return redirect(url_for('viz.index'))
    
    # Parse result data and convert to DataFrame - memory-efficient approach
    try:
        result_data = json.loads(result['result_data'])
        # Use smaller chunks to limit memory usage
        if VISUALIZATION_ENABLED:
            df = pd.DataFrame(result_data)
            # Get columns for selection
            columns = df.columns.tolist()
            numeric_columns = df.select_dtypes(include=[np.number]).columns.tolist()
        else:
            columns = []
            numeric_columns = []
    except Exception as e:
        flash(f'Error parsing result data: {str(e)}', 'error')
        return redirect(url_for('viz.index'))
    
    # Set form defaults
    default_name = f"Visualization for {query['name']}" if query else "New Visualization"
    
    if request.method == 'POST' and VISUALIZATION_ENABLED:
        # Get form data
        name = request.form.get('name', default_name)
        description = request.form.get('description', '')
        viz_type = request.form.get('viz_type', 'bar')
        x_column = request.form.get('x_column')
        y_column = request.form.get('y_column')
        color_column = request.form.get('color_column', '')
        
        try:
            # Create visualization config
            config = {
                'type': viz_type,
                'x_column': x_column,
                'y_column': y_column,
                'color_column': color_column if color_column else None,
                'title': name,
                'additional_options': _get_viz_options(viz_type, request.form)
            }
            
            # Create the visualization
            viz_id = create_visualization(name, description, viz_type, result_id, config)
            
            flash('Visualization created successfully!', 'success')
            return redirect(url_for('viz.view', viz_id=viz_id))
            
        except Exception as e:
            flash(f'Error creating visualization: {str(e)}', 'error')
    
    # GET request - show create form
    return render_template('visualization_create.html', 
                         result_id=result_id,
                         default_name=default_name,
                         columns=columns,
                         numeric_columns=numeric_columns,
                         viz_enabled=VISUALIZATION_ENABLED)

@viz_bp.route('/view/<int:viz_id>')
def view(viz_id):
    """View a visualization"""
    if not VISUALIZATION_ENABLED:
        flash('Visualization is disabled due to missing dependencies. Please install pandas, numpy, and plotly.', 'warning')
        return redirect(url_for('viz.index'))
        
    visualization = get_visualization_by_id(viz_id)
    if not visualization:
        flash('Visualization not found', 'error')
        return redirect(url_for('viz.index'))
    
    # Get result data - lazy loading analysis module
    try:
        from main import get_module
        analysis_module = get_module('analysis')
        if analysis_module:
            result = analysis_module.get_result_by_id(visualization['result_id'])
        else:
            flash('Analysis module not available', 'error')
            return redirect(url_for('viz.index'))
    except ImportError:
        flash('Analysis module not available', 'error')
        return redirect(url_for('viz.index'))
        
    if not result:
        flash('Result data not found', 'error')
        return redirect(url_for('viz.index'))
        
    # Process result data with memory-efficient approach
    try:
        result_data = json.loads(result['result_data'])
    except Exception as e:
        flash(f'Error parsing result data: {str(e)}', 'error')
        return redirect(url_for('viz.index'))
    
    # Generate the visualization
    try:
        if VISUALIZATION_ENABLED:
            fig = generate_visualization(result_data, visualization['config'])
            plot_json = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
        else:
            plot_json = None
    except Exception as e:
        flash(f'Error generating visualization: {str(e)}', 'error')
        return redirect(url_for('viz.index'))
    
    return render_template('visualization_view.html', 
                         visualization=visualization,
                         plot_json=plot_json,
                         viz_enabled=VISUALIZATION_ENABLED)

@viz_bp.route('/delete/<int:viz_id>', methods=['POST'])
def delete(viz_id):
    """Delete a visualization"""
    try:
        conn = _db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM visualizations WHERE id = ?", (viz_id,))
        conn.commit()
        conn.close()
        flash('Visualization deleted successfully', 'success')
    except Exception as e:
        flash(f'Error deleting visualization: {str(e)}', 'error')
    return redirect(url_for('viz.index'))

@viz_bp.route('/api/visualizations')
def api_visualizations():
    """API endpoint to get all visualizations with pagination"""
    limit = request.args.get('limit', 20, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    conn = _db_connection(sqlite3.Row)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT v.*, r.query_id, q.name as query_name
        FROM visualizations v
        LEFT JOIN analysis_results r ON v.result_id = r.id
        LEFT JOIN analysis_queries q ON r.query_id = q.id
        ORDER BY v.created_at DESC
        LIMIT ? OFFSET ?
    """, (limit, offset))
    
    visualizations = [dict(row) for row in cursor.fetchall()]
    
    # Parse config - but keep this lightweight
    for viz in visualizations:
        viz['config'] = json.loads(viz['config'])
    
    conn.close()
    return jsonify(visualizations)

@viz_bp.route('/api/visualization/<int:viz_id>')
def api_visualization(viz_id):
    """API endpoint to get a specific visualization"""
    visualization = get_visualization_by_id(viz_id)
    if not visualization:
        return jsonify({'error': 'Visualization not found'}), 404
    
    # Keep the response lightweight - don't include plot data
    return jsonify(visualization)

# Helper function to extract visualization options from form
def _get_viz_options(viz_type, form_data):
    """Extract visualization-specific options from form data"""
    if not VISUALIZATION_ENABLED:
        return {}
        
    options = {}
    
    if viz_type == 'bar':
        options['orientation'] = form_data.get('bar_orientation', 'v')
        options['barmode'] = form_data.get('barmode', 'group')
    elif viz_type == 'scatter':
        options['marker_size'] = form_data.get('marker_size', 6, type=int)
        options['trendline'] = 'trendline' in form_data
    elif viz_type == 'line':
        options['line_shape'] = form_data.get('line_shape', 'linear')
    elif viz_type == 'pie':
        options['hole'] = form_data.get('pie_hole', 0, type=float)
    elif viz_type == 'histogram':
        options['bins'] = form_data.get('histogram_bins', 10, type=int)
    
    return options

# Visualization functions
def generate_visualization(data, config):
    """Generate a visualization based on the data and configuration - memory-optimized"""
    if not VISUALIZATION_ENABLED:
        return None
        
    # Convert to DataFrame if needed - only if it's not too large
    if isinstance(data, list):
        # For large datasets, sample the data to reduce memory usage
        if len(data) > 1000:
            # Take a representative sample
            import random
            sampled_data = random.sample(data, 1000)
            df = pd.DataFrame(sampled_data)
        else:
            df = pd.DataFrame(data)
    else:
        df = data
    
    # Get visualization parameters
    viz_type = config.get('type', 'bar')
    x_column = config.get('x_column')
    y_column = config.get('y_column')
    color_column = config.get('color_column')
    title = config.get('title', 'Visualization')
    additional_options = config.get('additional_options', {})
    
    # Create the appropriate visualization
    if viz_type == 'bar':
        orientation = additional_options.get('orientation', 'v')
        barmode = additional_options.get('barmode', 'group')
        
        if orientation == 'h':
            fig = px.bar(df, y=x_column, x=y_column, color=color_column, 
                         title=title, orientation='h', barmode=barmode)
        else:
            fig = px.bar(df, x=x_column, y=y_column, color=color_column, 
                         title=title, barmode=barmode)
            
    elif viz_type == 'line':
        line_shape = additional_options.get('line_shape', 'linear')
        fig = px.line(df, x=x_column, y=y_column, color=color_column, 
                      title=title, line_shape=line_shape)
        
    elif viz_type == 'scatter':
        marker_size = additional_options.get('marker_size', 6)
        trendline = additional_options.get('trendline', False)
        
        fig = px.scatter(df, x=x_column, y=y_column, color=color_column, 
                         title=title, trendline='ols' if trendline else None)
        fig.update_traces(marker=dict(size=marker_size))
        
    elif viz_type == 'pie':
        hole = additional_options.get('hole', 0)
        fig = px.pie(df, names=x_column, values=y_column, title=title, hole=hole)
        
    elif viz_type == 'histogram':
        bins = additional_options.get('bins', 10)
        fig = px.histogram(df, x=x_column, color=color_column, title=title, nbins=bins)
        
    elif viz_type == 'heatmap':
        # For heatmap, we need to pivot the data
        try:
            # Limit the size of the pivot table
            if len(df) > 500:
                df = df.head(500)
            pivot_df = df.pivot(index=x_column, columns=color_column, values=y_column)
            fig = px.imshow(pivot_df, title=title)
        except Exception as e:
            # If pivot fails, fallback to a correlation heatmap
            numeric_df = df.select_dtypes(include=[np.number])
            fig = px.imshow(numeric_df.corr(), title=f"{title} (Correlation Matrix)")
    
    else:
        # Default to bar chart
        fig = px.bar(df, x=x_column, y=y_column, color=color_column, title=title)
    
    # Add interactive features - but keep it lightweight
    fig.update_layout(
        margin=dict(l=40, r=40, t=50, b=40),
        template='plotly_white',
        hovermode='closest',
        autosize=True
    )
    
    return fig

# Database operations - consolidated and optimized
def create_visualization(name, description, viz_type, result_id, config):
    """Create a new visualization"""
    conn = _db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            """
            INSERT INTO visualizations 
            (name, description, type, result_id, config, created_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (name, description, viz_type, result_id, json.dumps(config))
        )
        
        viz_id = cursor.lastrowid
        conn.commit()
        return viz_id
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_visualizations():
    """Get a list of visualizations with pagination for efficiency"""
    limit = request.args.get('limit', 20, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    conn = _db_connection(sqlite3.Row)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT v.*, r.query_id, q.name as query_name
        FROM visualizations v
        LEFT JOIN analysis_results r ON v.result_id = r.id
        LEFT JOIN analysis_queries q ON r.query_id = q.id
        ORDER BY v.created_at DESC
        LIMIT ? OFFSET ?
    """, (limit, offset))
    
    visualizations = [dict(row) for row in cursor.fetchall()]
    
    # Parse config
    for viz in visualizations:
        viz['config'] = json.loads(viz['config'])
    
    conn.close()
    return visualizations

def get_visualization_by_id(viz_id):
    """Get visualization information by ID"""
    conn = _db_connection(sqlite3.Row)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT v.*, r.query_id, q.name as query_name
        FROM visualizations v
        LEFT JOIN analysis_results r ON v.result_id = r.id
        LEFT JOIN analysis_queries q ON r.query_id = q.id
        WHERE v.id = ?
    """, (viz_id,))
    visualization = cursor.fetchone()
    
    conn.close()
    
    if visualization:
        # Convert to dict and parse config
        viz_dict = dict(visualization)
        viz_dict['config'] = json.loads(viz_dict['config'])
        return viz_dict
    else:
        return None

def get_visualizations_for_dashboard():
    """Get a small number of visualizations for the dashboard"""
    # Used by web_interface module
    conn = _db_connection(sqlite3.Row)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT v.id, v.name, v.type, v.created_at
        FROM visualizations v
        ORDER BY v.created_at DESC
        LIMIT 5
    """)
    
    visualizations = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return visualizations

# CSS generator - only called when explicitly requested
def generate_css():
    """Generate CSS for the visualization module"""
    # Skip if file already exists
    if os.path.exists('static/css/viz_module.css'):
        return
        
    css = """
    /* Visualization Module CSS - Minimal version */
    .viz-card { border: 1px solid #eaeaea; border-radius: 5px; padding: 15px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
    .viz-container { height: 500px; width: 100%; border-radius: 4px; overflow: hidden; }
    .viz-options { margin-bottom: 20px; }
    .viz-thumbnail { height: 200px; width: 100%; border: 1px solid #ddd; border-radius: 5px; overflow: hidden; }
    .viz-controls { display: flex; justify-content: space-between; margin-bottom: 15px; }
    """
    
    # Write CSS to file
    os.makedirs('static/css', exist_ok=True)
    with open('static/css/viz_module.css', 'w') as f:
        f.write(css)

# JS generator - only called when explicitly requested
def generate_js():
    """Generate JavaScript for the visualization module"""
    # Skip if file already exists
    if os.path.exists('static/js/viz_module.js'):
        return
        
    js = """
    // Visualization Module JavaScript - Minimal version
    document.addEventListener('DOMContentLoaded', function() {
        // Handle visualization type change
        const vizTypeSelect = document.getElementById('viz-type');
        if (vizTypeSelect) {
            vizTypeSelect.addEventListener('change', function() {
                const vizType = this.value;
                document.querySelectorAll('.viz-options-section').forEach(section => {
                    section.style.display = 'none';
                });
                const sectionToShow = document.getElementById(`${vizType}-options`);
                if (sectionToShow) {
                    sectionToShow.style.display = 'block';
                }
            });
        }
        
        // Handle fullscreen toggle
        const fullscreenBtn = document.getElementById('fullscreen-btn');
        if (fullscreenBtn) {
            fullscreenBtn.addEventListener('click', function() {
                const vizContainer = document.getElementById('visualization-container');
                vizContainer.classList.toggle('viz-fullscreen');
                window.dispatchEvent(new Event('resize'));
            });
        }
    });
    """
    
    # Write JS to file
    os.makedirs('static/js', exist_ok=True)
    with open('static/js/viz_module.js', 'w') as f:
        f.write(js)

# Template generator - only called when explicitly requested
def generate_templates():
    """Generate essential HTML templates for the visualization module"""
    # Skip if templates already exist
    if os.path.exists('templates/visualization_index.html'):
        return
        
    # Create templates directory
    os.makedirs('templates', exist_ok=True)
    
    # Create a basic template for when visualizations are disabled
    with open('templates/visualization_disabled.html', 'w') as f:
        f.write("""
        {% extends 'base.html' %}
        
        {% block title %}Visualizations Disabled{% endblock %}
        
        {% block content %}
        <div class="container mt-4">
            <div class="alert alert-warning">
                <h4>Visualization Module Disabled</h4>
                <p>The visualization module is currently disabled because the required dependencies are not installed.</p>
                <p>To enable visualizations, please install the following packages:</p>
                <ul>
                    <li>pandas</li>
                    <li>numpy</li>
                    <li>plotly</li>
                </ul>
                <p>You can install these by uncommenting them in requirements.txt and rebuilding the application.</p>
            </div>
            <a href="/" class="btn btn-primary">Return to Home</a>
        </div>
        {% endblock %}
        """)
    
    # Only generate the index template as a minimum requirement
    with open('templates/visualization_index.html', 'w') as f:
        f.write("""
        {% extends 'base.html' %}
        
        {% block title %}Visualizations{% endblock %}
        
        {% block content %}
        <div class="container mt-4">
            <div class="d-flex justify-content-between align-items-center mb-4">
                <h1>Visualizations</h1>
                <a href="{{ url_for('viz.create') }}" class="btn btn-primary">
                    <i class="fas fa-plus"></i> New Visualization
                </a>
            </div>
            
            {% with messages = get_flashed_messages(with_categories=true) %}
              {% if messages %}
                {% for category, message in messages %}
                  <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
              {% endif %}
            {% endwith %}
            
            {% if visualizations %}
                <div class="row">
                    {% for viz in visualizations %}
                    <div class="col-md-4 mb-4">
                        <div class="card viz-card">
                            <div class="card-body">
                                <h5 class="card-title">{{ viz.name }}</h5>
                                <p class="card-text"><small>{{ viz.type|title }} Chart</small></p>
                                <div class="d-flex justify-content-between">
                                    <a href="{{ url_for('viz.view', viz_id=viz.id) }}" class="btn btn-primary btn-sm">View</a>
                                    <form method="POST" action="{{ url_for('viz.delete', viz_id=viz.id) }}">
                                        <button type="submit" class="btn btn-danger btn-sm">Delete</button>
                                    </form>
                                </div>
                            </div>
                        </div>
                    </div>
                    {% endfor %}
                </div>
            {% else %}
                <div class="alert alert-info">No visualizations found.</div>
            {% endif %}
        </div>
        {% endblock %}
        """)
        
    # Create visualization view template
    with open('templates/visualization_view.html', 'w') as f:
        f.write("""
        {% extends 'base.html' %}
        
        {% block title %}{{ visualization.name }}{% endblock %}
        
        {% block head %}
        {{ super() }}
        <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
        {% endblock %}
        
        {% block content %}
        <div class="container mt-4">
            <div class="d-flex justify-content-between align-items-center mb-4">
                <h1>{{ visualization.name }}</h1>
                <div>
                    <a href="{{ url_for('viz.index') }}" class="btn btn-outline-secondary">Back to List</a>
                    <button id="fullscreen-btn" class="btn btn-outline-primary">
                        <i class="fas fa-expand"></i> Fullscreen
                    </button>
                </div>
            </div>
            
            {% with messages = get_flashed_messages(with_categories=true) %}
              {% if messages %}
                {% for category, message in messages %}
                  <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
              {% endif %}
            {% endwith %}
            
            {% if not viz_enabled %}
            <div class="alert alert-warning">
                <h4>Visualization Module Disabled</h4>
                <p>The visualization module is currently disabled because the required dependencies are not installed.</p>
            </div>
            {% else %}
            <div class="card mb-4">
                <div class="card-body">
                    <p>{{ visualization.description }}</p>
                    <div id="visualization-container" class="viz-container"></div>
                </div>
            </div>
            
            <div class="card">
                <div class="card-header">
                    Visualization Details
                </div>
                <div class="card-body">
                    <table class="table table-sm">
                        <tr>
                            <th>Type:</th>
                            <td>{{ visualization.type|title }} Chart</td>
                        </tr>
                        <tr>
                            <th>X Axis:</th>
                            <td>{{ visualization.config.x_column }}</td>
                        </tr>
                        <tr>
                            <th>Y Axis:</th>
                            <td>{{ visualization.config.y_column }}</td>
                        </tr>
                        {% if visualization.config.color_column %}
                        <tr>
                            <th>Color:</th>
                            <td>{{ visualization.config.color_column }}</td>
                        </tr>
                        {% endif %}
                        <tr>
                            <th>Created:</th>
                            <td>{{ visualization.created_at }}</td>
                        </tr>
                    </table>
                </div>
            </div>
            {% endif %}
        </div>
        
        {% if viz_enabled and plot_json %}
        <script>
            document.addEventListener('DOMContentLoaded', function() {
                var graphData = {{ plot_json|safe }};
                Plotly.newPlot('visualization-container', graphData.data, graphData.layout);
                
                window.addEventListener('resize', function() {
                    Plotly.relayout('visualization-container', {
                        'xaxis.autorange': true,
                        'yaxis.autorange': true
                    });
                });
            });
        </script>
        {% endif %}
        {% endblock %}
        """)
        
    # Create visualization create template
    with open('templates/visualization_create.html', 'w') as f:
        f.write("""
        {% extends 'base.html' %}
        
        {% block title %}Create Visualization{% endblock %}
        
        {% block content %}
        <div class="container mt-4">
            <div class="d-flex justify-content-between align-items-center mb-4">
                <h1>Create New Visualization</h1>
                <a href="{{ url_for('viz.index') }}" class="btn btn-outline-secondary">Back to List</a>
            </div>
            
            {% with messages = get_flashed_messages(with_categories=true) %}
              {% if messages %}
                {% for category, message in messages %}
                  <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
              {% endif %}
            {% endwith %}
            
            {% if not viz_enabled %}
            <div class="alert alert-warning">
                <h4>Visualization Module Disabled</h4>
                <p>The visualization module is currently disabled because the required dependencies are not installed.</p>
                <p>To enable visualizations, please install the following packages:</p>
                <ul>
                    <li>pandas</li>
                    <li>numpy</li>
                    <li>plotly</li>
                </ul>
            </div>
            {% else %}
            <div class="card">
                <div class="card-body">
                    <form method="POST" action="{{ url_for('viz.create', result_id=result_id) }}">
                        <div class="form-group mb-3">
                            <label for="name">Visualization Name</label>
                            <input type="text" class="form-control" id="name" name="name" value="{{ default_name }}" required>
                        </div>
                        
                        <div class="form-group mb-3">
                            <label for="description">Description</label>
                            <textarea class="form-control" id="description" name="description" rows="2"></textarea>
                        </div>
                        
                        <div class="form-group mb-3">
                            <label for="viz-type">Visualization Type</label>
                            <select class="form-control" id="viz-type" name="viz_type" required>
                                <option value="bar">Bar Chart</option>
                                <option value="line">Line Chart</option>
                                <option value="scatter">Scatter Plot</option>
                                <option value="pie">Pie Chart</option>
                                <option value="histogram">Histogram</option>
                                <option value="heatmap">Heatmap</option>
                            </select>
                        </div>
                        
                        <div class="form-group mb-3">
                            <label for="x_column">X Axis / Category</label>
                            <select class="form-control" id="x_column" name="x_column" required>
                                <option value="">Select a column</option>
                                {% for column in columns %}
                                <option value="{{ column }}">{{ column }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        
                        <div class="form-group mb-3">
                            <label for="y_column">Y Axis / Value</label>
                            <select class="form-control" id="y_column" name="y_column" required>
                                <option value="">Select a column</option>
                                {% for column in numeric_columns %}
                                <option value="{{ column }}">{{ column }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        
                        <div class="form-group mb-3">
                            <label for="color_column">Color / Group By (Optional)</label>
                            <select class="form-control" id="color_column" name="color_column">
                                <option value="">None</option>
                                {% for column in columns %}
                                <option value="{{ column }}">{{ column }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        
                        <!-- Visualization-specific options -->
                        <div id="bar-options" class="viz-options-section">
                            <h4>Bar Chart Options</h4>
                            <div class="form-group">
                                <label>Orientation</label>
                                <div class="form-check">
                                    <input class="form-check-input" type="radio" name="bar_orientation" id="vertical" value="v" checked>
                                    <label class="form-check-label" for="vertical">Vertical</label>
                                </div>
                                <div class="form-check">
                                    <input class="form-check-input" type="radio" name="bar_orientation" id="horizontal" value="h">
                                    <label class="form-check-label" for="horizontal">Horizontal</label>
                                </div>
                            </div>
                            
                            <div class="form-group">
                                <label for="barmode">Bar Mode</label>
                                <select class="form-control" id="barmode" name="barmode">
                                    <option value="group">Grouped</option>
                                    <option value="stack">Stacked</option>
                                </select>
                            </div>
                        </div>
                        
                        <div id="scatter-options" class="viz-options-section" style="display: none;">
                            <h4>Scatter Plot Options</h4>
                            <div class="form-group">
                                <label for="marker_size">Marker Size</label>
                                <input type="number" class="form-control" id="marker_size" name="marker_size" value="6" min="1" max="20">
                            </div>
                            
                            <div class="form-check">
                                <input class="form-check-input" type="checkbox" id="trendline" name="trendline">
                                <label class="form-check-label" for="trendline">Show Trendline</label>
                            </div>
                        </div>
                        
                        <div id="line-options" class="viz-options-section" style="display: none;">
                            <h4>Line Chart Options</h4>
                            <div class="form-group">
                                <label for="line_shape">Line Shape</label>
                                <select class="form-control" id="line_shape" name="line_shape">
                                    <option value="linear">Linear</option>
                                    <option value="spline">Spline (Curved)</option>
                                    <option value="hv">Step (HV)</option>
                                    <option value="vh">Step (VH)</option>
                                </select>
                            </div>
                        </div>
                        
                        <div id="pie-options" class="viz-options-section" style="display: none;">
                            <h4>Pie Chart Options</h4>
                            <div class="form-group">
                                <label for="pie_hole">Donut Hole Size (0-1)</label>
                                <input type="number" class="form-control" id="pie_hole" name="pie_hole" value="0" min="0" max="0.9" step="0.1">
                                <small class="form-text text-muted">0 for pie chart, > 0 for donut chart</small>
                            </div>
                        </div>
                        
                        <div id="histogram-options" class="viz-options-section" style="display: none;">
                            <h4>Histogram Options</h4>
                            <div class="form-group">
                                <label for="histogram_bins">Number of Bins</label>
                                <input type="number" class="form-control" id="histogram_bins" name="histogram_bins" value="10" min="5" max="50">
                            </div>
                        </div>
                        
                        <div id="heatmap-options" class="viz-options-section" style="display: none;">
                            <h4>Heatmap Options</h4>
                            <p class="text-muted">For heatmaps, X Axis will be used as rows, Color/Group as columns, and Y Axis as values.</p>
                        </div>
                        
                        <button type="submit" class="btn btn-primary">Create Visualization</button>
                    </form>
                </div>
            </div>
            {% endif %}
        </div>
        
        <script src="{{ url_for('static', filename='js/viz_module.js') }}"></script>
        {% endblock %}
        """)
        
    # Create visualization select data template
    with open('templates/visualization_select_data.html', 'w') as f:
        f.write("""
        {% extends 'base.html' %}
        
        {% block title %}Select Data{% endblock %}
        
        {% block content %}
        <div class="container mt-4">
            <div class="d-flex justify-content-between align-items-center mb-4">
                <h1>Select Data for Visualization</h1>
                <a href="{{ url_for('viz.index') }}" class="btn btn-outline-secondary">Back to List</a>
            </div>
            
            {% with messages = get_flashed_messages(with_categories=true) %}
              {% if messages %}
                {% for category, message in messages %}
                  <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
              {% endif %}
            {% endwith %}
            
            {% if recent_results %}
                <div class="card">
                    <div class="card-header">
                        Recent Analysis Results
                    </div>
                    <div class="card-body">
                        <p>Select a dataset to create a visualization:</p>
                        
                        <table class="table table-hover">
                            <thead>
                                <tr>
                                    <th>Dataset Name</th>
                                    <th>Created</th>
                                    <th>Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {% for result in recent_results %}
                                <tr>
                                    <td>{{ result.name }}</td>
                                    <td>{{ result.created_at }}</td>
                                    <td>
                                        <a href="{{ url_for('viz.create', result_id=result.id) }}" class="btn btn-sm btn-primary">Select</a>
                                    </td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                </div>
            {% else %}
                <div class="alert alert-info">
                    <p>No data available for visualization. Please run an analysis first.</p>
                    <a href="{{ url_for('analysis.index') }}" class="btn btn-primary">Go to Analysis</a>
                </div>
            {% endif %}
        </div>
        {% endblock %}
        """)
