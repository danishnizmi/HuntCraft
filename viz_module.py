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
    visualizations = get_visualizations()
    return render_template('visualization_index.html', visualizations=visualizations)

@viz_bp.route('/create', methods=['GET', 'POST'])
def create():
    """Create visualization form and handler"""
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
        df = pd.DataFrame(result_data)
    except Exception as e:
        flash(f'Error parsing result data: {str(e)}', 'error')
        return redirect(url_for('viz.index'))
    
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
        fig = generate_visualization(result_data, visualization['config'])
        plot_json = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
    except Exception as e:
        flash(f'Error generating visualization: {str(e)}', 'error')
        return redirect(url_for('viz.index'))
    
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
    
    # Only generate the index template as a minimum requirement
    index_template = """
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
    """
    
    # Write template to file
    with open('templates/visualization_index.html', 'w') as f:
        f.write(index_template)
