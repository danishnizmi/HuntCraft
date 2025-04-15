from flask import Blueprint, request, render_template, current_app, jsonify, flash, redirect, url_for
import pandas as pd
import numpy as np
import sqlite3
import os
import json
from datetime import datetime
import plotly
import plotly.express as px
import plotly.graph_objects as go

# Create blueprint with shorter name
viz_bp = Blueprint('viz', __name__, url_prefix='/viz')

def init_app(app):
    """Initialize the visualization module with the Flask app"""
    app.register_blueprint(viz_bp)
    
    # Generate CSS, JS, and templates
    with app.app_context():
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

# Helper function for DB connections to reduce repeated code
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
    visualizations = get_visualizations()
    return render_template('visualization_index.html', visualizations=visualizations)

@viz_bp.route('/create', methods=['GET', 'POST'])
def create():
    """Create visualization form and handler"""
    # Check if we're creating from an analysis result
    result_id = request.args.get('result_id', type=int)
    
    if not result_id:
        # No result specified, show available results
        from analysis_module import get_recent_results
        recent_results = get_recent_results(limit=10)
        return render_template('visualization_select_data.html', recent_results=recent_results)
    
    # Load result data
    from analysis_module import get_result_by_id, get_query_by_id
    result = get_result_by_id(result_id)
    
    if not result:
        flash('Analysis result not found', 'error')
        return redirect(url_for('viz.index'))
        
    # Get the query information
    query = get_query_by_id(result['query_id'])
    
    # Parse result data and convert to DataFrame
    result_data = json.loads(result['result_data'])
    df = pd.DataFrame(result_data)
    
    # Get columns for selection
    columns = df.columns.tolist()
    numeric_columns = df.select_dtypes(include=[np.number]).columns.tolist()
    
    # Set form defaults
    default_name = f"Visualization for {query['name']}" if query else "New Visualization"
    
    if request.method == 'POST':
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
                          numeric_columns=numeric_columns)

@viz_bp.route('/view/<int:viz_id>')
def view(viz_id):
    """View a visualization"""
    visualization = get_visualization_by_id(viz_id)
    if not visualization:
        flash('Visualization not found', 'error')
        return redirect(url_for('viz.index'))
    
    # Get result data
    from analysis_module import get_result_by_id
    result = get_result_by_id(visualization['result_id'])
    if not result:
        flash('Result data not found', 'error')
        return redirect(url_for('viz.index'))
        
    result_data = json.loads(result['result_data'])
    
    # Generate the visualization
    fig = generate_visualization(result_data, visualization['config'])
    
    # Convert to JSON for Plotly.js
    plot_json = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
    
    return render_template('visualization_view.html', 
                          visualization=visualization,
                          plot_json=plot_json)

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
    """API endpoint to get all visualizations"""
    visualizations = get_visualizations()
    return jsonify(visualizations)

@viz_bp.route('/api/visualization/<int:viz_id>')
def api_visualization(viz_id):
    """API endpoint to get a specific visualization"""
    visualization = get_visualization_by_id(viz_id)
    if not visualization:
        return jsonify({'error': 'Visualization not found'}), 404
    
    # Get result data
    from analysis_module import get_result_by_id
    result = get_result_by_id(visualization['result_id'])
    result_data = json.loads(result['result_data'])
    
    # Generate the visualization
    fig = generate_visualization(result_data, visualization['config'])
    
    # Add the plot data to the response
    visualization['plot_data'] = fig
    
    return jsonify(visualization)

# Helper function to extract visualization options from form
def _get_viz_options(viz_type, form_data):
    """Extract visualization-specific options from form data"""
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
    """
    Generate a visualization based on the data and configuration
    
    Args:
        data: The data to visualize (list of dicts or pandas DataFrame)
        config: Visualization configuration
        
    Returns:
        A Plotly figure object
    """
    # Convert to DataFrame if needed
    if isinstance(data, list):
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
            pivot_df = df.pivot(index=x_column, columns=color_column, values=y_column)
            fig = px.imshow(pivot_df, title=title)
        except Exception as e:
            # If pivot fails, fallback to a correlation heatmap
            numeric_df = df.select_dtypes(include=[np.number])
            fig = px.imshow(numeric_df.corr(), title=f"{title} (Correlation Matrix)")
    
    else:
        # Default to bar chart
        fig = px.bar(df, x=x_column, y=y_column, color=color_column, title=title)
    
    # Add interactive features
    fig.update_layout(
        margin=dict(l=40, r=40, t=50, b=40),
        template='plotly_white',
        hovermode='closest',
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        # Add modebar buttons
        modebar_add=["v1hovermode", "hoverclosest", "toggleSpikelines"]
    )
    
    # Make the chart responsive
    fig.update_layout(autosize=True)
    
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
    """Get a list of all visualizations"""
    conn = _db_connection(sqlite3.Row)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT v.*, r.query_id, q.name as query_name
        FROM visualizations v
        LEFT JOIN analysis_results r ON v.result_id = r.id
        LEFT JOIN analysis_queries q ON r.query_id = q.id
        ORDER BY v.created_at DESC
    """)
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

# Include CSS generator
def generate_css():
    """Generate enhanced CSS for the visualization module"""
    css = """
    /* Visualization Module CSS */
    .viz-card {
        border: 1px solid #eaeaea;
        border-radius: 5px;
        padding: 15px;
        margin-bottom: 20px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        transition: transform 0.2s ease-in-out, box-shadow 0.2s ease-in-out;
    }
    
    .viz-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 6px 12px rgba(0,0,0,0.15);
    }
    
    .viz-container {
        height: 500px;
        width: 100%;
        border-radius: 4px;
        overflow: hidden;
    }
    
    .viz-options {
        margin-bottom: 20px;
    }
    
    .viz-thumbnail {
        height: 200px;
        width: 100%;
        border: 1px solid #ddd;
        border-radius: 5px;
        overflow: hidden;
    }
    
    /* Enhanced visualization controls */
    .viz-controls {
        display: flex;
        justify-content: space-between;
        margin-bottom: 15px;
    }
    
    .viz-controls .btn-group {
        margin-right: 10px;
    }
    
    .viz-fullscreen {
        position: fixed;
        top: 0;
        left: 0;
        width: 100vw;
        height: 100vh;
        z-index: 9999;
        background: white;
        padding: 20px;
    }
    
    /* Responsive adjustments */
    @media (max-width: 768px) {
        .viz-container {
            height: 400px;
        }
        
        .viz-fullscreen {
            padding: 10px;
        }
    }
    
    /* Form enhancements */
    .viz-create-form {
        margin-bottom: 30px;
    }
    
    .viz-create-form label {
        font-weight: 500;
    }
    
    .viz-create-form .form-select, 
    .viz-create-form .form-control {
        border-radius: 4px;
        border: 1px solid #ced4da;
    }
    
    .viz-create-form .form-select:focus, 
    .viz-create-form .form-control:focus {
        border-color: var(--primary-color);
        box-shadow: 0 0 0 0.25rem rgba(74, 111, 165, 0.25);
    }
    
    .viz-options-section {
        padding: 15px;
        background-color: #f8f9fa;
        border-radius: 4px;
        margin-bottom: 20px;
    }
    
    /* Animation for page loading */
    @keyframes fadeIn {
        from { opacity: 0; }
        to { opacity: 1; }
    }
    
    .viz-fade-in {
        animation: fadeIn 0.5s ease-in-out;
    }
    
    /* Tooltip styling */
    .viz-tooltip {
        position: relative;
        display: inline-block;
    }
    
    .viz-tooltip .viz-tooltip-text {
        visibility: hidden;
        width: 200px;
        background-color: #333;
        color: #fff;
        text-align: center;
        border-radius: 4px;
        padding: 5px;
        position: absolute;
        z-index: 1;
        bottom: 125%;
        left: 50%;
        transform: translateX(-50%);
        opacity: 0;
        transition: opacity 0.3s;
    }
    
    .viz-tooltip:hover .viz-tooltip-text {
        visibility: visible;
        opacity: 1;
    }
    """
    
    # Write CSS to file
    os.makedirs('static/css', exist_ok=True)
    with open('static/css/viz_module.css', 'w') as f:
        f.write(css)

# Include JS generator
def generate_js():
    """Generate enhanced JavaScript for the visualization module"""
    js = """
    // Visualization Module JavaScript
    document.addEventListener('DOMContentLoaded', function() {
        // Handle visualization type change to show appropriate options
        const vizTypeSelect = document.getElementById('viz-type');
        if (vizTypeSelect) {
            vizTypeSelect.addEventListener('change', function() {
                updateVizOptions(this.value);
            });
            // Initial update
            updateVizOptions(vizTypeSelect.value);
        }
        
        // Handle delete confirmation
        const deleteButtons = document.querySelectorAll('.delete-viz-btn');
        if (deleteButtons) {
            deleteButtons.forEach(button => {
                button.addEventListener('click', function(e) {
                    if (!confirm('Are you sure you want to delete this visualization? This action cannot be undone.')) {
                        e.preventDefault();
                    }
                });
            });
        }
        
        // Handle fullscreen toggle
        const fullscreenBtn = document.getElementById('fullscreen-btn');
        if (fullscreenBtn) {
            fullscreenBtn.addEventListener('click', function() {
                const vizContainer = document.getElementById('visualization-container');
                vizContainer.classList.toggle('viz-fullscreen');
                this.innerHTML = vizContainer.classList.contains('viz-fullscreen') ? 
                    '<i class="fas fa-compress"></i> Exit Fullscreen' : 
                    '<i class="fas fa-expand"></i> Fullscreen';
                
                // Force Plotly to resize
                window.dispatchEvent(new Event('resize'));
            });
        }
        
        // Handle visualization download
        const downloadBtn = document.getElementById('download-btn');
        if (downloadBtn && typeof Plotly !== 'undefined') {
            downloadBtn.addEventListener('click', function() {
                const vizContainer = document.getElementById('visualization-container');
                Plotly.downloadImage(vizContainer, {
                    format: 'png',
                    filename: 'visualization',
                    width: 1200,
                    height: 800
                });
            });
        }
        
        // Add event listeners to range inputs to update their displayed values
        document.querySelectorAll('input[type="range"]').forEach(range => {
            const valueDisplay = document.createElement('span');
            valueDisplay.className = 'ms-2 badge bg-primary';
            valueDisplay.textContent = range.value;
            
            range.parentNode.appendChild(valueDisplay);
            
            range.addEventListener('input', function() {
                valueDisplay.textContent = this.value;
            });
        });
        
        // Add keyboard shortcut for fullscreen (F key)
        document.addEventListener('keydown', function(e) {
            if (e.key === 'f' && fullscreenBtn) {
                fullscreenBtn.click();
                e.preventDefault();
            }
        });
    });
    
    function updateVizOptions(vizType) {
        // Hide all option sections
        document.querySelectorAll('.viz-options-section').forEach(section => {
            section.style.display = 'none';
        });
        
        // Show the appropriate section
        const sectionToShow = document.getElementById(`${vizType}-options`);
        if (sectionToShow) {
            sectionToShow.style.display = 'block';
        }
        
        // Update form elements based on selection
        const yColumnSelect = document.getElementById('y_column');
        if (yColumnSelect) {
            // For pie charts, make y_column required and update label
            if (vizType === 'pie') {
                document.querySelector('label[for="y_column"]').textContent = 'Values Column';
                document.querySelector('label[for="x_column"]').textContent = 'Labels Column';
            } else {
                document.querySelector('label[for="y_column"]').textContent = 'Y-Axis Column';
                document.querySelector('label[for="x_column"]').textContent = 'X-Axis Column';
            }
        }
    }
    
    // Function to dynamically create a simple preview
    function createVizPreview(containerId, vizType, data) {
        if (!window.Plotly) return;
        
        let traces = [];
        let layout = {
            margin: {t:5, l:5, r:5, b:5},
            showlegend: false,
            paper_bgcolor: '#f8f9fa',
            plot_bgcolor: '#f8f9fa'
        };
        
        switch(vizType) {
            case 'bar':
                traces = [{
                    type: 'bar',
                    x: ['A', 'B', 'C', 'D'],
                    y: [3, 1, 5, 2],
                    marker: {color: '#4a6fa5'}
                }];
                break;
            case 'line':
                traces = [{
                    type: 'scatter',
                    mode: 'lines',
                    x: [1, 2, 3, 4, 5],
                    y: [1, 3, 2, 4, 3],
                    line: {color: '#4a6fa5'}
                }];
                break;
            case 'scatter':
                traces = [{
                    type: 'scatter',
                    mode: 'markers',
                    x: [1, 2, 3, 4, 5],
                    y: [1, 3, 2, 4, 3],
                    marker: {color: '#4a6fa5'}
                }];
                break;
            case 'pie':
                traces = [{
                    type: 'pie',
                    labels: ['A', 'B', 'C'],
                    values: [3, 2, 5],
                    marker: {colors: ['#4a6fa5', '#6c757d', '#28a745']}
                }];
                break;
            default:
                traces = [{
                    type: 'bar',
                    x: ['A', 'B', 'C'],
                    y: [1, 2, 3],
                    marker: {color: '#4a6fa5'}
                }];
        }
        
        Plotly.newPlot(containerId, traces, layout, {
            displayModeBar: false,
            responsive: true
        });
    }
    """
    
    # Write JS to file
    os.makedirs('static/js', exist_ok=True)
    with open('static/js/viz_module.js', 'w') as f:
        f.write(js)

# Include template generator with all required templates
def generate_templates():
    """Generate all templates for the visualization module"""
    # Create the directory if it doesn't exist
    os.makedirs('templates', exist_ok=True)
    
    # Template 1: Visualization Index
    index_template = """
    {% extends 'base.html' %}
    
    {% block title %}Visualizations{% endblock %}
    
    {% block styles %}
    <link href="{{ url_for('static', filename='css/viz_module.css') }}" rel="stylesheet">
    {% endblock %}
    
    {% block content %}
    <div class="container mt-4 viz-fade-in">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h1>Visualizations</h1>
            <a href="{{ url_for('viz.create') }}" class="btn btn-primary">
                <i class="fas fa-plus"></i> New Visualization
            </a>
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
        
        <div class="row">
            {% if visualizations %}
                {% for viz in visualizations %}
                <div class="col-md-4 mb-4">
                    <div class="card viz-card h-100">
                        <div class="viz-thumbnail">
                            <div id="viz-thumbnail-{{ viz.id }}" class="h-100"></div>
                        </div>
                        <div class="card-body">
                            <h5 class="card-title">{{ viz.name }}</h5>
                            <p class="card-text text-muted small">
                                <i class="fas fa-chart-{{ 'bar' if viz.type == 'bar' else 'line' if viz.type == 'line' else 'pie' if viz.type == 'pie' else 'scatter' if viz.type == 'scatter' else 'bar' }}"></i> 
                                {{ viz.type|title }} Chart
                            </p>
                            <p class="card-text">{{ viz.description or 'No description' }}</p>
                            <p class="card-text"><small class="text-muted">Created {{ viz.created_at|format_timestamp }}</small></p>
                        </div>
                        <div class="card-footer bg-transparent">
                            <div class="d-flex justify-content-between">
                                <a href="{{ url_for('viz.view', viz_id=viz.id) }}" class="btn btn-primary btn-sm">
                                    <i class="fas fa-eye"></i> View
                                </a>
                                <form method="POST" action="{{ url_for('viz.delete', viz_id=viz.id) }}" class="d-inline">
                                    <button type="submit" class="btn btn-danger btn-sm delete-viz-btn">
                                        <i class="fas fa-trash"></i> Delete
                                    </button>
                                </form>
                            </div>
                        </div>
                    </div>
                </div>
                {% endfor %}
            {% else %}
                <div class="col-12">
                    <div class="alert alert-info">
                        <p>No visualizations found. Create a new visualization to get started.</p>
                        <a href="{{ url_for('viz.create') }}" class="btn btn-primary mt-2">
                            <i class="fas fa-plus"></i> Create Visualization
                        </a>
                    </div>
                </div>
            {% endif %}
        </div>
    </div>
    {% endblock %}
    
    {% block scripts %}
    <script src="{{ url_for('static', filename='js/viz_module.js') }}"></script>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <script>
        document.addEventListener('DOMContentLoaded', function() {
            // Create mini thumbnails for each visualization
            {% for viz in visualizations %}
                // Basic thumbnail representation based on visualization type
                createVizPreview('viz-thumbnail-{{ viz.id }}', '{{ viz.config.type }}');
            {% endfor %}
        });
    </script>
    {% endblock %}
    """
    
    # Template 2: Visualization View
    view_template = """
    {% extends 'base.html' %}
    
    {% block title %}{{ visualization.name }}{% endblock %}
    
    {% block styles %}
    <link href="{{ url_for('static', filename='css/viz_module.css') }}" rel="stylesheet">
    {% endblock %}
    
    {% block content %}
    <div class="container mt-4 viz-fade-in">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h1>{{ visualization.name }}</h1>
            <div>
                <a href="{{ url_for('viz.index') }}" class="btn btn-secondary">
                    <i class="fas fa-arrow-left"></i> Back to Visualizations
                </a>
            </div>
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
        
        <div class="card mb-4">
            <div class="card-body">
                <div class="viz-controls mb-3">
                    <div class="btn-group">
                        <button type="button" id="fullscreen-btn" class="btn btn-outline-primary">
                            <i class="fas fa-expand"></i> Fullscreen
                        </button>
                        <button type="button" id="download-btn" class="btn btn-outline-primary">
                            <i class="fas fa-download"></i> Download
                        </button>
                    </div>
                    <div class="viz-tooltip">
                        <i class="fas fa-info-circle text-muted"></i>
                        <span class="viz-tooltip-text">
                            Press 'F' key for fullscreen. Use mouse to interact with the chart.
                        </span>
                    </div>
                </div>
                <div class="viz-container" id="visualization-container"></div>
            </div>
        </div>
        
        <div class="row">
            <div class="col-md-6">
                <div class="card mb-4">
                    <div class="card-header">
                        <h5 class="mb-0">Visualization Information</h5>
                    </div>
                    <div class="card-body">
                        <dl class="row mb-0">
                            <dt class="col-sm-4">Name:</dt>
                            <dd class="col-sm-8">{{ visualization.name }}</dd>
                            
                            <dt class="col-sm-4">Description:</dt>
                            <dd class="col-sm-8">{{ visualization.description or 'No description' }}</dd>
                            
                            <dt class="col-sm-4">Type:</dt>
                            <dd class="col-sm-8">
                                <i class="fas fa-chart-{{ 'bar' if visualization.type == 'bar' else 'line' if visualization.type == 'line' else 'pie' if visualization.type == 'pie' else 'scatter' if visualization.type == 'scatter' else 'bar' }}"></i> 
                                {{ visualization.type|title }} Chart
                            </dd>
                            
                            <dt class="col-sm-4">Created:</dt>
                            <dd class="col-sm-8">{{ visualization.created_at|format_timestamp }}</dd>
                        </dl>
                    </div>
                </div>
            </div>
            <div class="col-md-6">
                <div class="card mb-4">
                    <div class="card-header">
                        <h5 class="mb-0">Data Information</h5>
                    </div>
                    <div class="card-body">
                        <dl class="row mb-0">
                            <dt class="col-sm-4">Data Source:</dt>
                            <dd class="col-sm-8">{{ visualization.query_name }}</dd>
                            
                            <dt class="col-sm-4">X-Axis:</dt>
                            <dd class="col-sm-8">{{ visualization.config.x_column }}</dd>
                            
                            <dt class="col-sm-4">Y-Axis:</dt>
                            <dd class="col-sm-8">{{ visualization.config.y_column }}</dd>
                            
                            {% if visualization.config.color_column %}
                            <dt class="col-sm-4">Color:</dt>
                            <dd class="col-sm-8">{{ visualization.config.color_column }}</dd>
                            {% endif %}
                        </dl>
                    </div>
                </div>
            </div>
        </div>
    </div>
    {% endblock %}
    
    {% block scripts %}
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <script src="{{ url_for('static', filename='js/viz_module.js') }}"></script>
    <script>
        document.addEventListener('DOMContentLoaded', function() {
            // Initialize the visualization
            const plotData = {{ plot_json|safe }};
            Plotly.newPlot('visualization-container', plotData.data, plotData.layout, {
                responsive: true,
                toImageButtonOptions: {
                    format: 'png',
                    filename: '{{ visualization.name|replace(" ", "_") }}',
                    height: 800,
                    width: 1200,
                    scale: 1
                }
            });
        });
    </script>
    {% endblock %}
    """
    
    # Template 3: Visualization Create Form
    create_template = """
    {% extends 'base.html' %}
    
    {% block title %}Create Visualization{% endblock %}
    
    {% block styles %}
    <link href="{{ url_for('static', filename='css/viz_module.css') }}" rel="stylesheet">
    {% endblock %}
    
    {% block content %}
    <div class="container mt-4 viz-fade-in">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h1>Create Visualization</h1>
            <a href="{{ url_for('viz.index') }}" class="btn btn-secondary">
                <i class="fas fa-arrow-left"></i> Back to Visualizations
            </a>
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
        
        <div class="card mb-4">
            <div class="card-body">
                <form method="POST" class="viz-create-form">
                    <input type="hidden" name="result_id" value="{{ result_id }}">
                    
                    <div class="row mb-3">
                        <div class="col-md-6">
                            <label for="name" class="form-label">Visualization Name</label>
                            <input type="text" class="form-control" id="name" name="name" value="{{ default_name }}" required>
                        </div>
                        <div class="col-md-6">
                            <label for="viz-type" class="form-label">Visualization Type</label>
                            <select class="form-select" id="viz-type" name="viz_type" required>
                                <option value="bar">Bar Chart</option>
                                <option value="line">Line Chart</option>
                                <option value="scatter">Scatter Plot</option>
                                <option value="pie">Pie Chart</option>
                                <option value="histogram">Histogram</option>
                                <option value="heatmap">Heatmap</option>
                            </select>
                        </div>
                    </div>
                    
                    <div class="mb-3">
                        <label for="description" class="form-label">Description</label>
                        <textarea class="form-control" id="description" name="description" rows="2" placeholder="Optional description of this visualization"></textarea>
                    </div>
                    
                    <div class="row mb-3">
                        <div class="col-md-4">
                            <label for="x_column" class="form-label">X-Axis Column</label>
                            <select class="form-select" id="x_column" name="x_column" required>
                                {% for column in columns %}
                                <option value="{{ column }}">{{ column }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        <div class="col-md-4">
                            <label for="y_column" class="form-label">Y-Axis Column</label>
                            <select class="form-select" id="y_column" name="y_column" required>
                                {% for column in numeric_columns %}
                                <option value="{{ column }}">{{ column }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        <div class="col-md-4">
                            <label for="color_column" class="form-label">Color Column (Optional)</label>
                            <select class="form-select" id="color_column" name="color_column">
                                <option value="">None</option>
                                {% for column in columns %}
                                <option value="{{ column }}">{{ column }}</option>
                                {% endfor %}
                            </select>
                        </div>
                    </div>
                    
                    <!-- Type-specific options sections -->
                    
                    <!-- Bar Chart Options -->
                    <div id="bar-options" class="viz-options-section">
                        <h5 class="mb-3">Bar Chart Options</h5>
                        <div class="row">
                            <div class="col-md-6">
                                <label class="form-label">Bar Orientation</label>
                                <div class="form-check">
                                    <input class="form-check-input" type="radio" name="bar_orientation" id="bar-orientation-v" value="v" checked>
                                    <label class="form-check-label" for="bar-orientation-v">
                                        Vertical Bars
                                    </label>
                                </div>
                                <div class="form-check">
                                    <input class="form-check-input" type="radio" name="bar_orientation" id="bar-orientation-h" value="h">
                                    <label class="form-check-label" for="bar-orientation-h">
                                        Horizontal Bars
                                    </label>
                                </div>
                            </div>
                            <div class="col-md-6">
                                <label class="form-label">Bar Mode</label>
                                <div class="form-check">
                                    <input class="form-check-input" type="radio" name="barmode" id="barmode-group" value="group" checked>
                                    <label class="form-check-label" for="barmode-group">
                                        Grouped
                                    </label>
                                </div>
                                <div class="form-check">
                                    <input class="form-check-input" type="radio" name="barmode" id="barmode-stack" value="stack">
                                    <label class="form-check-label" for="barmode-stack">
                                        Stacked
                                    </label>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Line Chart Options -->
                    <div id="line-options" class="viz-options-section" style="display:none;">
                        <h5 class="mb-3">Line Chart Options</h5>
                        <div class="mb-3">
                            <label class="form-label">Line Shape</label>
                            <select class="form-select" name="line_shape">
                                <option value="linear">Linear</option>
                                <option value="spline">Spline (Curved)</option>
                                <option value="hv">Step (Horizontal First)</option>
                                <option value="vh">Step (Vertical First)</option>
                            </select>
                        </div>
                    </div>
                    
                    <!-- Scatter Plot Options -->
                    <div id="scatter-options" class="viz-options-section" style="display:none;">
                        <h5 class="mb-3">Scatter Plot Options</h5>
                        <div class="mb-3">
                            <label for="marker-size" class="form-label">Marker Size</label>
                            <input type="range" class="form-range" id="marker-size" name="marker_size" min="2" max="20" value="6">
                        </div>
                        <div class="form-check mb-3">
                            <input class="form-check-input" type="checkbox" id="trendline" name="trendline">
                            <label class="form-check-label" for="trendline">
                                Show Trendline
                            </label>
                        </div>
                    </div>
                    
                    <!-- Pie Chart Options -->
                    <div id="pie-options" class="viz-options-section" style="display:none;">
                        <h5 class="mb-3">Pie Chart Options</h5>
                        <div class="mb-3">
                            <label for="pie-hole" class="form-label">Donut Hole Size (0-1)</label>
                            <input type="range" class="form-range" id="pie-hole" name="pie_hole" min="0" max="0.8" step="0.1" value="0">
                        </div>
                    </div>
                    
                    <!-- Histogram Options -->
                    <div id="histogram-options" class="viz-options-section" style="display:none;">
                        <h5 class="mb-3">Histogram Options</h5>
                        <div class="mb-3">
                            <label for="histogram-bins" class="form-label">Number of Bins</label>
                            <input type="range" class="form-range" id="histogram-bins" name="histogram_bins" min="5" max="50" step="1" value="10">
                        </div>
                    </div>
                    
                    <!-- Heatmap Options -->
                    <div id="heatmap-options" class="viz-options-section" style="display:none;">
                        <h5 class="mb-3">Heatmap Options</h5>
                        <div class="alert alert-info">
                            <i class="fas fa-info-circle"></i> For heatmaps, the X-Axis is used as the row index, Color Column as the column index, and Y-Axis as the values.
                        </div>
                    </div>
                    
                    <div class="mt-4">
                        <button type="submit" class="btn btn-primary">
                            <i class="fas fa-chart-bar"></i> Create Visualization
                        </button>
                        <a href="{{ url_for('viz.index') }}" class="btn btn-outline-secondary ms-2">Cancel</a>
                    </div>
                </form>
            </div>
        </div>
        
        <div class="card">
            <div class="card-header">
                <h5 class="mb-0">Visualization Preview</h5>
            </div>
            <div class="card-body text-center">
                <div id="viz-preview" style="height: 300px;"></div>
                <p class="text-muted mt-2">This is a generic preview. The actual visualization will use your selected data.</p>
            </div>
        </div>
    </div>
    {% endblock %}
    
    {% block scripts %}
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <script src="{{ url_for('static', filename='js/viz_module.js') }}"></script>
    <script>
        document.addEventListener('DOMContentLoaded', function() {
            // Generate initial preview
            createVizPreview('viz-preview', document.getElementById('viz-type').value);
            
            // Update preview when visualization type changes
            document.getElementById('viz-type').addEventListener('change', function() {
                createVizPreview('viz-preview', this.value);
            });
        });
    </script>
    {% endblock %}
    """
    
    # Template 4: Select Data for Visualization
    select_data_template = """
    {% extends 'base.html' %}
    
    {% block title %}Select Data for Visualization{% endblock %}
    
    {% block styles %}
    <link href="{{ url_for('static', filename='css/viz_module.css') }}" rel="stylesheet">
    {% endblock %}
    
    {% block content %}
    <div class="container mt-4 viz-fade-in">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h1>Select Data for Visualization</h1>
            <a href="{{ url_for('viz.index') }}" class="btn btn-secondary">
                <i class="fas fa-arrow-left"></i> Back to Visualizations
            </a>
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
        
        <div class="card">
            <div class="card-header">
                <h5 class="mb-0">Recent Analysis Results</h5>
            </div>
            <div class="card-body">
                {% if recent_results %}
                    <div class="table-responsive">
                        <table class="table table-hover">
                            <thead>
                                <tr>
                                    <th>Query Name</th>
                                    <th>Result Type</th>
                                    <th>Row Count</th>
                                    <th>Created</th>
                                    <th>Action</th>
                                </tr>
                            </thead>
                            <tbody>
                                {% for result in recent_results %}
                                <tr>
                                    <td>{{ result.query_name }}</td>
                                    <td>
                                        <span class="badge bg-{{ 'primary' if result.result_type == 'dataframe' else 'success' if result.result_type == 'aggregation' else 'secondary' }}">
                                            {{ result.result_type|title }}
                                        </span>
                                    </td>
                                    <td>{{ result.row_count }}</td>
                                    <td>{{ result.created_at|format_timestamp }}</td>
                                    <td>
                                        <a href="{{ url_for('viz.create', result_id=result.id) }}" class="btn btn-primary btn-sm">
                                            <i class="fas fa-chart-bar"></i> Visualize
                                        </a>
                                    </td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                {% else %}
                    <div class="alert alert-info">
                        <p>No analysis results found. Run an analysis to create visualizations.</p>
                        <a href="{{ url_for('analysis.index') }}" class="btn btn-primary mt-2">
                            <i class="fas fa-search"></i> Go to Analysis
                        </a>
                    </div>
                {% endif %}
            </div>
        </div>
        
        <div class="row mt-4">
            <div class="col-md-6">
                <div class="card">
                    <div class="card-header">
                        <h5 class="mb-0">Visualization Types</h5>
                    </div>
                    <div class="card-body">
                        <div class="row text-center">
                            <div class="col-md-4 mb-3">
                                <div class="p-3 border rounded">
                                    <i class="fas fa-chart-bar fa-2x mb-2 text-primary"></i>
                                    <h6>Bar Chart</h6>
                                    <p class="small text-muted">Compare values across categories</p>
                                </div>
                            </div>
                            <div class="col-md-4 mb-3">
                                <div class="p-3 border rounded">
                                    <i class="fas fa-chart-line fa-2x mb-2 text-primary"></i>
                                    <h6>Line Chart</h6>
                                    <p class="small text-muted">Show trends over time</p>
                                </div>
                            </div>
                            <div class="col-md-4 mb-3">
                                <div class="p-3 border rounded">
                                    <i class="fas fa-chart-pie fa-2x mb-2 text-primary"></i>
                                    <h6>Pie Chart</h6>
                                    <p class="small text-muted">Show proportions of a whole</p>
                                </div>
                            </div>
                            <div class="col-md-4 mb-3">
                                <div class="p-3 border rounded">
                                    <i class="fas fa-braille fa-2x mb-2 text-primary"></i>
                                    <h6>Scatter Plot</h6>
                                    <p class="small text-muted">Show relationships between variables</p>
                                </div>
                            </div>
                            <div class="col-md-4 mb-3">
                                <div class="p-3 border rounded">
                                    <i class="fas fa-chart-area fa-2x mb-2 text-primary"></i>
                                    <h6>Histogram</h6>
                                    <p class="small text-muted">Show distribution of data</p>
                                </div>
                            </div>
                            <div class="col-md-4 mb-3">
                                <div class="p-3 border rounded">
                                    <i class="fas fa-th fa-2x mb-2 text-primary"></i>
                                    <h6>Heatmap</h6>
                                    <p class="small text-muted">Show patterns in matrix data</p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            <div class="col-md-6">
                <div class="card">
                    <div class="card-header">
                        <h5 class="mb-0">Tips for Effective Visualizations</h5>
                    </div>
                    <div class="card-body">
                        <ul class="list-group list-group-flush">
                            <li class="list-group-item">
                                <i class="fas fa-check-circle text-success"></i> 
                                Choose the right visualization type for your data
                            </li>
                            <li class="list-group-item">
                                <i class="fas fa-check-circle text-success"></i> 
                                Use color to highlight important information
                            </li>
                            <li class="list-group-item">
                                <i class="fas fa-check-circle text-success"></i> 
                                Keep it simple and focused on one key message
                            </li>
                            <li class="list-group-item">
                                <i class="fas fa-check-circle text-success"></i> 
                                Use clear labels and titles to explain your data
                            </li>
                            <li class="list-group-item">
                                <i class="fas fa-check-circle text-success"></i> 
                                Consider your audience when designing visualizations
                            </li>
                        </ul>
                    </div>
                </div>
            </div>
        </div>
    </div>
    {% endblock %}
    
    {% block scripts %}
    <script src="{{ url_for('static', filename='js/viz_module.js') }}"></script>
    {% endblock %}
    """
    
    # Write the templates to files
    with open('templates/visualization_index.html', 'w') as f:
        f.write(index_template)
        
    with open('templates/visualization_view.html', 'w') as f:
        f.write(view_template)
        
    with open('templates/visualization_create.html', 'w') as f:
        f.write(create_template)
        
    with open('templates/visualization_select_data.html', 'w') as f:
        f.write(select_data_template)
