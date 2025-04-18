from flask import Blueprint, request, render_template, current_app, jsonify, flash, redirect, url_for
import os
import json
import sqlite3
import logging
from datetime import datetime

# Set up logger first to capture import errors
logger = logging.getLogger(__name__)

# Create blueprint immediately
viz_bp = Blueprint('viz', __name__, url_prefix='/viz')

# Try to import visualization dependencies with better error handling
VISUALIZATION_ENABLED = False
BASIC_DEPS_AVAILABLE = False

try:
    import pandas as pd
    import numpy as np
    BASIC_DEPS_AVAILABLE = True

    # Try to import plotly separately - we can still provide basic visualizations without it
    try:
        import plotly
        import plotly.express as px
        import plotly.graph_objects as go
        VISUALIZATION_ENABLED = True
        logger.info("Full visualization capabilities available (pandas, numpy, plotly)")
    except ImportError:
        logger.warning("Plotly not available. Basic visualization will be used instead.")
except ImportError:
    logger.warning("Visualization dependencies not available. Install pandas, numpy, and plotly for full functionality.")

def init_app(app):
    """Initialize the visualization module with the Flask app"""
    # Register blueprint first to avoid initialization issues
    try:
        app.register_blueprint(viz_bp)
        logger.info("Visualization blueprint registered successfully")
    except Exception as e:
        logger.error(f"Failed to register visualization blueprint: {e}")
        raise
    
    # Continue with other initialization in a safer way
    try:
        # Generate templates and static files
        with app.app_context():
            if app.config.get('GENERATE_TEMPLATES', False):
                generate_templates()
                generate_css()
                generate_js()
                logger.info("Visualization templates and static files generated")
        
        # Register template filter for formatting JSON
        @app.template_filter('pprint')
        def pprint_filter(value):
            try:
                return json.dumps(value, indent=2)
            except:
                return str(value)
        
        logger.info("Visualization module initialized successfully")
    except Exception as e:
        logger.error(f"Error in visualization module initialization: {e}")
        # Don't re-raise to allow app to start with limited functionality

def create_database_schema(cursor):
    """Create the necessary database tables for the visualization module"""
    try:
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS visualizations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            type TEXT NOT NULL,
            result_id INTEGER,
            config TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (result_id) REFERENCES malware_samples(id)
        )
        ''')
        logger.info("Visualization database schema created successfully")
    except Exception as e:
        logger.error(f"Error creating visualization database schema: {e}")
        raise

def _db_connection(row_factory=None):
    """Create a database connection with optional row factory"""
    try:
        from database import get_db_connection
        return get_db_connection(row_factory)
    except ImportError:
        # Fallback if database.py is not available
        try:
            conn = sqlite3.connect(current_app.config['DATABASE_PATH'])
            if row_factory:
                conn.row_factory = row_factory
            return conn
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            raise

def execute_query(query, params=(), fetch_one=False, commit=False):
    """Execute a database query with unified error handling"""
    try:
        from database import execute_query as db_execute_query
        return db_execute_query(query, params, fetch_one, commit)
    except ImportError:
        # Fallback if database.py is not available
        db = _db_connection()
        cursor = db.cursor()
        
        try:
            cursor.execute(query, params)
            
            if fetch_one:
                result = cursor.fetchone()
            elif not commit:
                result = cursor.fetchall()
            else:
                result = None
                
            if commit:
                db.commit()
                
            return result
        except Exception as e:
            if commit:
                db.rollback()
            logger.error(f"Error executing query: {str(e)}\nQuery: {query}\nParams: {params}")
            raise
        finally:
            db.close()

# Routes
@viz_bp.route('/')
def index():
    """Visualization module main page"""
    if not BASIC_DEPS_AVAILABLE and not VISUALIZATION_ENABLED:
        flash('Visualization is disabled due to missing dependencies. Please install pandas, numpy, and plotly.', 'warning')
        return render_template('visualization_disabled.html')
    
    try:
        visualizations = get_visualizations()
        return render_template('visualization_index.html', 
                               visualizations=visualizations,
                               viz_enabled=VISUALIZATION_ENABLED)
    except Exception as e:
        logger.error(f"Error in visualization index: {e}")
        flash(f"Error loading visualizations: {str(e)}", "error")
        return render_template('visualization_index.html', 
                               visualizations=[],
                               viz_enabled=VISUALIZATION_ENABLED)

@viz_bp.route('/create', methods=['GET', 'POST'])
def create():
    """Create visualization form and handler"""
    if not BASIC_DEPS_AVAILABLE and not VISUALIZATION_ENABLED:
        flash('Visualization is disabled due to missing dependencies. Please install pandas, numpy, and plotly.', 'warning')
        return redirect(url_for('viz.index'))
        
    # Check if we're creating from an analysis result
    result_id = request.args.get('result_id', type=int)
    
    if not result_id:
        # No result specified, show available results
        try:
            # Use lazy loading for malware module
            from main import get_module
            malware_module = get_module('malware')
            if malware_module and hasattr(malware_module, 'get_recent_samples'):
                recent_results = malware_module.get_recent_samples(limit=10)
            else:
                recent_results = []
        except Exception as e:
            logger.error(f"Error importing malware module: {e}")
            recent_results = []
            
        return render_template('visualization_select_data.html', 
                               recent_results=recent_results,
                               viz_enabled=VISUALIZATION_ENABLED)
    
    # Load result data
    try:
        from main import get_module
        malware_module = get_module('malware')
        if malware_module:
            sample = malware_module.get_malware_by_id(result_id)
            if not sample:
                flash('Sample not found', 'error')
                return redirect(url_for('viz.index'))
        else:
            flash('Malware module not available', 'error')
            return redirect(url_for('viz.index'))
    except Exception as e:
        logger.error(f"Error loading sample data: {e}")
        flash('Error loading sample data', 'error')
        return redirect(url_for('viz.index'))
    
    # Parse sample data and set defaults for visualization creation
    columns = []
    numeric_columns = []
    
    try:
        sample_data = []
        if 'analysis_results' in sample and sample['analysis_results']:
            try:
                sample_data = json.loads(sample['analysis_results'])
            except:
                sample_data = [{'error': 'Invalid JSON data'}]
        
        # Convert to DataFrame for column selection if pandas is available
        if BASIC_DEPS_AVAILABLE and sample_data:
            try:
                if isinstance(sample_data, dict):
                    # Convert dict to DataFrame-friendly format
                    df_data = []
                    for key, value in sample_data.items():
                        if isinstance(value, dict):
                            row = {'name': key}
                            row.update(value)
                            df_data.append(row)
                        else:
                            df_data.append({'name': key, 'value': value})
                    df = pd.DataFrame(df_data)
                else:
                    df = pd.DataFrame(sample_data)
                
                # Get columns for selection
                columns = df.columns.tolist()
                numeric_columns = df.select_dtypes(include=[np.number]).columns.tolist() if not df.empty else []
            except Exception as e:
                logger.error(f"Error creating DataFrame: {e}")
                # Fallback to simple column extraction if DataFrame creation fails
                if isinstance(sample_data, list) and len(sample_data) > 0:
                    columns = list(sample_data[0].keys())
                elif isinstance(sample_data, dict):
                    columns = list(sample_data.keys())
        else:
            # Without pandas, try basic extraction of columns
            if isinstance(sample_data, list) and len(sample_data) > 0:
                columns = list(sample_data[0].keys())
            elif isinstance(sample_data, dict):
                columns = list(sample_data.keys())
    except Exception as e:
        logger.error(f"Error parsing sample data: {e}")
        columns = []
        numeric_columns = []
    
    # Set form defaults
    default_name = f"Visualization for {sample['name']}" if sample else "New Visualization"
    
    if request.method == 'POST':
        # Handle form submission
        try:
            # Get form data
            name = request.form.get('name', default_name)
            description = request.form.get('description', '')
            viz_type = request.form.get('viz_type', 'bar')
            x_column = request.form.get('x_column')
            y_column = request.form.get('y_column')
            color_column = request.form.get('color_column', '')
            
            # Create visualization config
            config = {
                'type': viz_type,
                'x_column': x_column,
                'y_column': y_column,
                'color_column': color_column if color_column else None,
                'title': name,
                'additional_options': _get_viz_options(viz_type, request.form),
                'fallback': not VISUALIZATION_ENABLED
            }
            
            # Create the visualization - this will work even without full dependencies
            viz_id = create_visualization(name, description, viz_type, result_id, config)
            
            flash('Visualization created successfully!', 'success')
            return redirect(url_for('viz.view', viz_id=viz_id))
        except Exception as e:
            logger.error(f"Error creating visualization: {e}")
            flash(f'Error creating visualization: {str(e)}', 'error')
    
    # GET request - show create form
    return render_template('visualization_create.html', 
                           result_id=result_id,
                           default_name=default_name,
                           columns=columns,
                           numeric_columns=numeric_columns,
                           viz_enabled=VISUALIZATION_ENABLED,
                           basic_deps=BASIC_DEPS_AVAILABLE,
                           sample=sample)

@viz_bp.route('/view/<int:viz_id>')
def view(viz_id):
    """View a visualization"""
    if not BASIC_DEPS_AVAILABLE and not VISUALIZATION_ENABLED:
        flash('Visualization is disabled due to missing dependencies. Please install pandas, numpy, and plotly.', 'warning')
        return redirect(url_for('viz.index'))
        
    visualization = get_visualization_by_id(viz_id)
    if not visualization:
        flash('Visualization not found', 'error')
        return redirect(url_for('viz.index'))
    
    # Get sample data
    try:
        from main import get_module
        malware_module = get_module('malware')
        if malware_module:
            sample = malware_module.get_malware_by_id(visualization['result_id'])
        else:
            flash('Malware module not available', 'error')
            return redirect(url_for('viz.index'))
    except Exception as e:
        logger.error(f"Error loading sample data: {e}")
        flash('Error loading sample data', 'error')
        return redirect(url_for('viz.index'))
        
    if not sample:
        flash('Sample data not found', 'error')
        return redirect(url_for('viz.index'))
    
    # Process sample data
    try:
        sample_data = []
        if 'analysis_results' in sample and sample['analysis_results']:
            try:
                sample_data = json.loads(sample['analysis_results'])
            except:
                sample_data = [{'error': 'Invalid JSON data'}]
    except Exception as e:
        logger.error(f"Error parsing sample data: {e}")
        flash(f'Error parsing sample data: {str(e)}', 'error')
        return redirect(url_for('viz.index'))
    
    # Generate the visualization
    try:
        if VISUALIZATION_ENABLED and sample_data:
            fig = generate_visualization(sample_data, visualization['config'])
            plot_json = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
        elif BASIC_DEPS_AVAILABLE and sample_data:
            # Generate a basic fallback visualization with less interactivity
            fig = generate_basic_visualization(sample_data, visualization['config'])
            try:
                plot_json = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
            except:
                plot_json = json.dumps(fig)
        else:
            plot_json = None
    except Exception as e:
        logger.error(f"Error generating visualization: {e}")
        flash(f'Error generating visualization: {str(e)}', 'error')
        plot_json = None
    
    return render_template('visualization_view.html', 
                           visualization=visualization,
                           plot_json=plot_json,
                           viz_enabled=VISUALIZATION_ENABLED,
                           basic_deps=BASIC_DEPS_AVAILABLE,
                           sample=sample)

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
        logger.error(f"Error deleting visualization: {e}")
        flash(f'Error deleting visualization: {str(e)}', 'error')
    return redirect(url_for('viz.index'))

@viz_bp.route('/api/visualizations')
def api_visualizations():
    """API endpoint to get all visualizations with pagination"""
    limit = request.args.get('limit', 20, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    try:
        conn = _db_connection(sqlite3.Row)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT v.*, s.name as sample_name
            FROM visualizations v
            LEFT JOIN malware_samples s ON v.result_id = s.id
            ORDER BY v.created_at DESC
            LIMIT ? OFFSET ?
        """, (limit, offset))
        
        visualizations = [dict(row) for row in cursor.fetchall()]
        
        # Parse config
        for viz in visualizations:
            try:
                viz['config'] = json.loads(viz['config'])
            except:
                viz['config'] = {}
        
        conn.close()
        return jsonify(visualizations)
    except Exception as e:
        logger.error(f"Error in API visualizations: {e}")
        return jsonify({"error": str(e)}), 500

@viz_bp.route('/api/visualization/<int:viz_id>')
def api_visualization(viz_id):
    """API endpoint to get a specific visualization"""
    visualization = get_visualization_by_id(viz_id)
    if not visualization:
        return jsonify({'error': 'Visualization not found'}), 404
    
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
    if not VISUALIZATION_ENABLED:
        return generate_basic_visualization(data, config)
        
    # Convert to DataFrame if needed
    if isinstance(data, dict):
        # Convert dict to DataFrame-friendly format
        df_data = []
        for key, value in data.items():
            if isinstance(value, dict):
                row = {'name': key}
                row.update(value)
                df_data.append(row)
            else:
                df_data.append({'name': key, 'value': value})
        df = pd.DataFrame(df_data)
    elif isinstance(data, list):
        # For large datasets, sample to reduce memory usage
        if len(data) > 1000:
            import random
            sampled_data = random.sample(data, 1000)
            df = pd.DataFrame(sampled_data)
        else:
            df = pd.DataFrame(data)
    else:
        df = pd.DataFrame([{'error': 'Invalid data format'}])
    
    # Get visualization parameters
    viz_type = config.get('type', 'bar')
    x_column = config.get('x_column')
    y_column = config.get('y_column')
    color_column = config.get('color_column')
    title = config.get('title', 'Visualization')
    additional_options = config.get('additional_options', {})
    
    # Check if the columns exist
    if x_column not in df.columns:
        return {"data": [], "layout": {"title": f"Error: Column '{x_column}' not found"}}
    if y_column not in df.columns:
        return {"data": [], "layout": {"title": f"Error: Column '{y_column}' not found"}}
    if color_column and color_column not in df.columns:
        color_column = None
    
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
            logger.error(f"Error creating heatmap: {e}")
            # If pivot fails, fallback to a correlation heatmap
            try:
                numeric_df = df.select_dtypes(include=[np.number])
                fig = px.imshow(numeric_df.corr(), title=f"{title} (Correlation Matrix)")
            except Exception as e:
                logger.error(f"Error creating correlation heatmap: {e}")
                return {"data": [], "layout": {"title": f"Error creating heatmap: {str(e)}"}}
    
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

def generate_basic_visualization(data, config):
    """Generate a basic visualization when Plotly is not available"""
    if not BASIC_DEPS_AVAILABLE:
        # Return a placeholder when even pandas/numpy are not available
        return {
            "data": [],
            "layout": {
                "title": "Visualization Not Available - Missing Dependencies",
                "annotations": [{
                    "text": "Please install pandas, numpy, and plotly packages.",
                    "showarrow": False,
                    "font": {"size": 14}
                }]
            }
        }
    
    # Basic visualization using pandas without plotly
    try:
        # Convert to DataFrame if needed
        if isinstance(data, dict):
            df_data = []
            for key, value in data.items():
                if isinstance(value, dict):
                    row = {'name': key}
                    row.update(value)
                    df_data.append(row)
                else:
                    df_data.append({'name': key, 'value': value})
            df = pd.DataFrame(df_data)
        elif isinstance(data, list):
            if len(data) > 1000:
                import random
                sampled_data = random.sample(data, 1000)
                df = pd.DataFrame(sampled_data)
            else:
                df = pd.DataFrame(data)
        else:
            return {
                "data": [],
                "layout": {"title": "Error: Invalid data format"}
            }
        
        # Get visualization parameters
        viz_type = config.get('type', 'bar')
        x_column = config.get('x_column')
        y_column = config.get('y_column')
        color_column = config.get('color_column')
        title = config.get('title', 'Visualization')
        
        # Check if the columns exist
        if x_column not in df.columns:
            return {"data": [], "layout": {"title": f"Error: Column '{x_column}' not found"}}
        if y_column not in df.columns:
            return {"data": [], "layout": {"title": f"Error: Column '{y_column}' not found"}}
        
        # Create a simple JSON-serializable data structure for the visualization
        # This is a simplified format that can be rendered with basic JavaScript
        data_points = []
        
        # Group by color if specified
        if color_column and color_column in df.columns:
            groups = df.groupby(color_column)
            
            for name, group in groups:
                series = {
                    "name": str(name),
                    "x": group[x_column].tolist(),
                    "y": group[y_column].tolist(),
                    "type": viz_type
                }
                data_points.append(series)
        else:
            # Single series
            series = {
                "name": y_column,
                "x": df[x_column].tolist(),
                "y": df[y_column].tolist(),
                "type": viz_type
            }
            data_points.append(series)
        
        # Create layout
        layout = {
            "title": title,
            "xaxis": {"title": x_column},
            "yaxis": {"title": y_column},
            "fallback": True  # Indicate this is a fallback visualization
        }
        
        return {
            "data": data_points,
            "layout": layout
        }
    except Exception as e:
        logger.error(f"Error generating basic visualization: {e}")
        return {
            "data": [],
            "layout": {
                "title": f"Error generating visualization: {str(e)}",
                "fallback": True
            }
        }

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
    
    try:
        conn = _db_connection(sqlite3.Row)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT v.*, s.name as sample_name
            FROM visualizations v
            LEFT JOIN malware_samples s ON v.result_id = s.id
            ORDER BY v.created_at DESC
            LIMIT ? OFFSET ?
        """, (limit, offset))
        
        visualizations = [dict(row) for row in cursor.fetchall()]
        
        # Parse config
        for viz in visualizations:
            try:
                viz['config'] = json.loads(viz['config'])
            except:
                viz['config'] = {}
        
        conn.close()
        return visualizations
    except Exception as e:
        logger.error(f"Error getting visualizations: {e}")
        return []

def get_visualization_by_id(viz_id):
    """Get visualization information by ID"""
    try:
        conn = _db_connection(sqlite3.Row)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT v.*, s.name as sample_name
            FROM visualizations v
            LEFT JOIN malware_samples s ON v.result_id = s.id
            WHERE v.id = ?
        """, (viz_id,))
        visualization = cursor.fetchone()
        
        conn.close()
        
        if visualization:
            # Convert to dict and parse config
            viz_dict = dict(visualization)
            try:
                viz_dict['config'] = json.loads(viz_dict['config'])
            except:
                viz_dict['config'] = {}
            return viz_dict
        else:
            return None
    except Exception as e:
        logger.error(f"Error getting visualization by ID: {e}")
        return None

def get_visualizations_for_dashboard():
    """Get a small number of visualizations for the dashboard"""
    # Used by web_interface module
    try:
        conn = _db_connection(sqlite3.Row)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT v.id, v.name, v.type, v.created_at, s.name as sample_name
            FROM visualizations v
            LEFT JOIN malware_samples s ON v.result_id = s.id
            ORDER BY v.created_at DESC
            LIMIT 5
        """)
        
        visualizations = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return visualizations
    except Exception as e:
        logger.error(f"Error getting dashboard visualizations: {e}")
        return []

# CSS generator - only called when explicitly requested
def generate_css():
    """Generate CSS for the visualization module"""
    # Skip if file already exists
    if os.path.exists('static/css/viz_module.css'):
        return
        
    css = """
    /* Visualization Module CSS */
    .viz-card { border: 1px solid #eaeaea; border-radius: 5px; padding: 15px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
    .viz-container { height: 500px; width: 100%; border-radius: 4px; overflow: hidden; }
    .viz-options { margin-bottom: 20px; }
    .viz-thumbnail { height: 200px; width: 100%; border: 1px solid #ddd; border-radius: 5px; overflow: hidden; }
    .viz-controls { display: flex; justify-content: space-between; margin-bottom: 15px; }
    .viz-fullscreen { position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; z-index: 1050; background: white; padding: 20px; }
    .viz-placeholder { display: flex; align-items: center; justify-content: center; height: 100%; background-color: #f5f5f5; color: #666; text-align: center; padding: 20px; }
    .viz-placeholder i { font-size: 3rem; margin-bottom: 15px; color: #aaa; }
    .viz-placeholder-message { margin-top: 15px; }
    """
    
    # Write CSS to file
    try:
        os.makedirs('static/css', exist_ok=True)
        with open('static/css/viz_module.css', 'w') as f:
            f.write(css)
        logger.info("Created visualization CSS file")
    except Exception as e:
        logger.error(f"Error generating CSS: {e}")

# JS generator - only called when explicitly requested
def generate_js():
    """Generate JavaScript for the visualization module"""
    # Skip if file already exists
    if os.path.exists('static/js/viz_module.js'):
        return
        
    js = """
    // Visualization Module JavaScript
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

        // Fallback visualization renderer - for when Plotly is not available
        const fallbackContainer = document.getElementById('fallback-visualization-container');
        if (fallbackContainer) {
            const dataElement = document.getElementById('visualization-data');
            if (dataElement) {
                try {
                    const vizData = JSON.parse(dataElement.textContent);
                    if (vizData && vizData.layout && vizData.layout.fallback) {
                        renderFallbackVisualization(fallbackContainer, vizData);
                    }
                } catch (e) {
                    console.error('Error parsing visualization data:', e);
                    fallbackContainer.innerHTML = '<div class="viz-placeholder"><p>Error loading visualization data</p></div>';
                }
            }
        }
    });

    // Simple fallback visualization renderer
    function renderFallbackVisualization(container, vizData) {
        if (!vizData || !vizData.data || !vizData.layout) {
            container.innerHTML = '<div class="viz-placeholder"><p>No visualization data available</p></div>';
            return;
        }

        const title = vizData.layout.title || 'Visualization';
        const xAxisTitle = vizData.layout.xaxis?.title || '';
        const yAxisTitle = vizData.layout.yaxis?.title || '';
        
        // Create a table representation of the data
        let tableHtml = `
            <div class="card">
                <div class="card-header">${title}</div>
                <div class="card-body">
                    <div class="table-responsive">
                        <table class="table table-sm table-striped">
                            <thead>
                                <tr>
                                    <th>${xAxisTitle}</th>
                                    <th>${yAxisTitle}</th>
                                </tr>
                            </thead>
                            <tbody>
        `;
        
        // Add rows for each data point (limited to 100 for performance)
        const maxRows = 100;
        let rowCount = 0;
        
        vizData.data.forEach(series => {
            if (series.x && series.y) {
                for (let i = 0; i < Math.min(series.x.length, maxRows - rowCount); i++) {
                    tableHtml += `<tr><td>${series.x[i]}</td><td>${series.y[i]}</td></tr>`;
                    rowCount++;
                }
            }
        });
        
        if (rowCount >= maxRows) {
            tableHtml += `<tr><td colspan="2" class="text-muted text-center">Showing ${maxRows} of ${vizData.data.reduce((sum, series) => sum + (series.x ? series.x.length : 0), 0)} data points</td></tr>`;
        }
        
        tableHtml += `
                            </tbody>
                        </table>
                    </div>
                    <div class="alert alert-info mt-3">
                        <i class="fas fa-info-circle"></i> 
                        This is a simplified view of the data. Install Plotly for interactive visualizations.
                    </div>
                </div>
            </div>
        `;
        
        container.innerHTML = tableHtml;
    }
    """
    
    # Write JS to file
    try:
        os.makedirs('static/js', exist_ok=True)
        with open('static/js/viz_module.js', 'w') as f:
            f.write(js)
        logger.info("Created visualization JS file")
    except Exception as e:
        logger.error(f"Error generating JS: {e}")

# Template generator
def generate_templates():
    """Generate essential HTML templates for the visualization module"""
    templates = {
        'visualization_disabled.html': """
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
""",

        'visualization_index.html': """
{% extends 'base.html' %}

{% block title %}Visualizations{% endblock %}

{% block head %}
{{ super() }}
<link href="{{ url_for('static', filename='css/viz_module.css') }}" rel="stylesheet">
{% endblock %}

{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4">
    <h1>Visualizations</h1>
    <a href="{{ url_for('viz.create') }}" class="btn btn-primary">
        <i class="fas fa-plus"></i> New Visualization
    </a>
</div>

{% if not viz_enabled %}
<div class="alert alert-warning">
    <h4><i class="fas fa-exclamation-triangle"></i> Limited Visualization Mode</h4>
    <p>The full visualization capabilities are not available because some dependencies are missing.</p>
    <p>Basic visualization functionality is still available, but for the best experience, please install the required packages: pandas, numpy, and plotly.</p>
</div>
{% endif %}

{% if visualizations %}
    <div class="row">
        {% for viz in visualizations %}
        <div class="col-md-4 mb-4">
            <div class="card viz-card">
                <div class="card-body">
                    <h5 class="card-title">{{ viz.name }}</h5>
                    <p class="card-text text-muted">{{ viz.type|title }} Chart</p>
                    <p class="card-text"><small>Sample: {{ viz.sample_name or "Unknown" }}</small></p>
                    <div class="d-flex justify-content-between">
                        <a href="{{ url_for('viz.view', viz_id=viz.id) }}" class="btn btn-primary btn-sm">View</a>
                        <form method="POST" action="{{ url_for('viz.delete', viz_id=viz.id) }}">
                            <button type="submit" class="btn btn-danger btn-sm" data-confirm="Are you sure you want to delete this visualization?">Delete</button>
                        </form>
                    </div>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
{% else %}
    <div class="alert alert-info">No visualizations found. Create a new visualization to get started.</div>
{% endif %}
{% endblock %}
""",

        'visualization_create.html': """
{% extends 'base.html' %}

{% block title %}Create Visualization{% endblock %}

{% block head %}
{{ super() }}
<link href="{{ url_for('static', filename='css/viz_module.css') }}" rel="stylesheet">
<script src="{{ url_for('static', filename='js/viz_module.js') }}" defer></script>
{% endblock %}

{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4">
    <h1>Create New Visualization</h1>
    <a href="{{ url_for('viz.index') }}" class="btn btn-outline-secondary">Back to List</a>
</div>

{% if not basic_deps %}
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
{% elif not viz_enabled %}
<div class="alert alert-warning">
    <h4><i class="fas fa-exclamation-triangle"></i> Limited Visualization Mode</h4>
    <p>The full visualization capabilities are not available because Plotly is missing.</p>
    <p>Basic visualization functionality is still available, but for the best experience, please install Plotly.</p>
</div>
{% endif %}

<div class="card mb-4">
    <div class="card-header bg-primary text-white">
        <h5 class="card-title mb-0">Sample: {{ sample.name }}</h5>
    </div>
    <div class="card-body">
        <div class="row">
            <div class="col-md-6">
                <p><strong>SHA256:</strong> <span class="hash-value">{{ sample.sha256 }}</span></p>
                <p><strong>Type:</strong> {{ sample.file_type }}</p>
            </div>
            <div class="col-md-6">
                <p><strong>Size:</strong> {{ sample.file_size }}</p>
                <p><strong>Uploaded:</strong> {{ sample.created_at }}</p>
            </div>
        </div>
    </div>
</div>

<div class="card">
    <div class="card-header bg-primary text-white">
        <h5 class="card-title mb-0">Visualization Settings</h5>
    </div>
    <div class="card-body">
        <form method="POST" action="{{ url_for('viz.create', result_id=result_id) }}">
            <div class="mb-3">
                <label for="name" class="form-label">Visualization Name</label>
                <input type="text" class="form-control" id="name" name="name" value="{{ default_name }}" required>
            </div>
            
            <div class="mb-3">
                <label for="description" class="form-label">Description</label>
                <textarea class="form-control" id="description" name="description" rows="2"></textarea>
            </div>
            
            <div class="mb-3">
                <label for="viz-type" class="form-label">Visualization Type</label>
                <select class="form-control" id="viz-type" name="viz_type" required>
                    <option value="bar">Bar Chart</option>
                    <option value="line">Line Chart</option>
                    <option value="scatter">Scatter Plot</option>
                    <option value="pie">Pie Chart</option>
                    <option value="histogram">Histogram</option>
                    <option value="heatmap">Heatmap</option>
                </select>
            </div>
            
            <div class="mb-3">
                <label for="x_column" class="form-label">X Axis / Category</label>
                <select class="form-control" id="x_column" name="x_column" required>
                    <option value="">Select a column</option>
                    {% for column in columns %}
                    <option value="{{ column }}">{{ column }}</option>
                    {% endfor %}
                </select>
            </div>
            
            <div class="mb-3">
                <label for="y_column" class="form-label">Y Axis / Value</label>
                <select class="form-control" id="y_column" name="y_column" required>
                    <option value="">Select a column</option>
                    {% for column in numeric_columns %}
                    <option value="{{ column }}">{{ column }}</option>
                    {% endfor %}
                    {% for column in columns %}
                        {% if column not in numeric_columns %}
                        <option value="{{ column }}">{{ column }} (non-numeric)</option>
                        {% endif %}
                    {% endfor %}
                </select>
            </div>
            
            <div class="mb-3">
                <label for="color_column" class="form-label">Color / Group By (Optional)</label>
                <select class="form-control" id="color_column" name="color_column">
                    <option value="">None</option>
                    {% for column in columns %}
                    <option value="{{ column }}">{{ column }}</option>
                    {% endfor %}
                </select>
            </div>
            
            <!-- Visualization-specific options -->
            <div id="bar-options" class="viz-options-section">
                <h5>Bar Chart Options</h5>
                <div class="mb-3">
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
                
                <div class="mb-3">
                    <label for="barmode">Bar Mode</label>
                    <select class="form-control" id="barmode" name="barmode">
                        <option value="group">Grouped</option>
                        <option value="stack">Stacked</option>
                    </select>
                </div>
            </div>
            
            <div id="scatter-options" class="viz-options-section" style="display: none;">
                <h5>Scatter Plot Options</h5>
                <div class="mb-3">
                    <label for="marker_size">Marker Size</label>
                    <input type="number" class="form-control" id="marker_size" name="marker_size" value="6" min="1" max="20">
                </div>
                
                <div class="form-check mb-3">
                    <input class="form-check-input" type="checkbox" id="trendline" name="trendline">
                    <label class="form-check-label" for="trendline">Show Trendline</label>
                </div>
            </div>
            
            <div id="line-options" class="viz-options-section" style="display: none;">
                <h5>Line Chart Options</h5>
                <div class="mb-3">
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
                <h5>Pie Chart Options</h5>
                <div class="mb-3">
                    <label for="pie_hole">Donut Hole Size (0-1)</label>
                    <input type="number" class="form-control" id="pie_hole" name="pie_hole" value="0" min="0" max="0.9" step="0.1">
                    <small class="form-text text-muted">0 for pie chart, > 0 for donut chart</small>
                </div>
            </div>
            
            <div id="histogram-options" class="viz-options-section" style="display: none;">
                <h5>Histogram Options</h5>
                <div class="mb-3">
                    <label for="histogram_bins">Number of Bins</label>
                    <input type="number" class="form-control" id="histogram_bins" name="histogram_bins" value="10" min="5" max="50">
                </div>
            </div>
            
            <div id="heatmap-options" class="viz-options-section" style="display: none;">
                <h5>Heatmap Options</h5>
                <p class="text-muted">For heatmaps, X Axis will be used as rows, Color/Group as columns, and Y Axis as values.</p>
            </div>
            
            <button type="submit" class="btn btn-primary">Create Visualization</button>
        </form>
    </div>
</div>
{% endblock %}
""",

        'visualization_view.html': """
{% extends 'base.html' %}

{% block title %}{{ visualization.name }}{% endblock %}

{% block head %}
{{ super() }}
<link href="{{ url_for('static', filename='css/viz_module.css') }}" rel="stylesheet">
{% if viz_enabled %}
<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
{% endif %}
<script src="{{ url_for('static', filename='js/viz_module.js') }}" defer></script>
{% endblock %}

{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4">
    <h1>{{ visualization.name }}</h1>
    <div>
        <a href="{{ url_for('viz.index') }}" class="btn btn-outline-secondary">Back to List</a>
        <button id="fullscreen-btn" class="btn btn-outline-primary">
            <i class="fas fa-expand"></i> Fullscreen
        </button>
    </div>
</div>

{% if not basic_deps %}
<div class="alert alert-warning">
    <h4>Visualization Module Disabled</h4>
    <p>The visualization module is currently disabled because the required dependencies are not installed.</p>
</div>
{% elif not viz_enabled %}
<div class="alert alert-warning">
    <h4><i class="fas fa-exclamation-triangle"></i> Limited Visualization Mode</h4>
    <p>The full visualization capabilities are not available because Plotly is missing.</p>
    <p>A simplified view of the data is shown below. For the best experience, please install Plotly.</p>
</div>
{% endif %}

<div class="row">
    <div class="col-md-8">
        <div class="card mb-4">
            <div class="card-body">
                {% if viz_enabled and plot_json %}
                <div id="visualization-container" class="viz-container"></div>
                {% else %}
                <div id="fallback-visualization-container" class="viz-container">
                    <div class="viz-placeholder">
                        <div class="text-center">
                            <i class="fas fa-chart-bar"></i>
                            <h4>Visualization Not Available</h4>
                            <p class="viz-placeholder-message">Install visualization dependencies for full functionality.</p>
                        </div>
                    </div>
                </div>
                <script id="visualization-data" type="application/json">{{ plot_json|safe }}</script>
                {% endif %}
            </div>
        </div>
    </div>
    <div class="col-md-4">
        <div class="card mb-4">
            <div class="card-header bg-primary text-white">
                <h5 class="card-title mb-0">Visualization Details</h5>
            </div>
            <div class="card-body">
                <p>{{ visualization.description }}</p>
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
                
                <div class="d-grid gap-2 mt-3">
                    <form method="POST" action="{{ url_for('viz.delete', viz_id=visualization.id) }}">
                        <button type="submit" class="btn btn-danger w-100" data-confirm="Are you sure you want to delete this visualization?">
                            <i class="fas fa-trash"></i> Delete Visualization
                        </button>
                    </form>
                </div>
            </div>
        </div>
        
        <div class="card">
            <div class="card-header bg-primary text-white">
                <h5 class="card-title mb-0">Sample Information</h5>
            </div>
            <div class="card-body">
                <h6>{{ sample.name }}</h6>
                <p><strong>SHA256:</strong> <span class="hash-value">{{ sample.sha256[:16] }}...</span></p>
                <p><strong>Type:</strong> {{ sample.file_type }}</p>
                <a href="{{ url_for('malware.view', sample_id=sample.id) }}" class="btn btn-sm btn-outline-primary">
                    View Sample Details
                </a>
            </div>
        </div>
    </div>
</div>
{% endblock %}

{% block scripts %}
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
""",

        'visualization_select_data.html': """
{% extends 'base.html' %}

{% block title %}Select Data{% endblock %}

{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4">
    <h1>Select Data for Visualization</h1>
    <a href="{{ url_for('viz.index') }}" class="btn btn-outline-secondary">Back to List</a>
</div>

{% if not viz_enabled %}
<div class="alert alert-warning">
    <h4><i class="fas fa-exclamation-triangle"></i> Limited Visualization Mode</h4>
    <p>The full visualization capabilities are not available because some dependencies are missing.</p>
    <p>Basic visualization functionality is still available, but for the best experience, please install the required packages: pandas, numpy, and plotly.</p>
</div>
{% endif %}

{% if recent_results %}
    <div class="card">
        <div class="card-header bg-primary text-white">
            <h5 class="card-title mb-0">Recent Malware Samples</h5>
        </div>
        <div class="card-body">
            <p>Select a sample to create a visualization:</p>
            
            <div class="table-responsive">
                <table class="table table-hover">
                    <thead>
                        <tr>
                            <th>Name</th>
                            <th>Type</th>
                            <th>SHA256</th>
                            <th>Uploaded</th>
                            <th>Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for result in recent_results %}
                        <tr>
                            <td>{{ result.name }}</td>
                            <td>{{ result.file_type }}</td>
                            <td><span class="hash-value">{{ result.sha256[:16] }}...</span></td>
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
    </div>
{% else %}
    <div class="alert alert-info">
        <p>No malware samples available for visualization. Please upload samples first.</p>
        <a href="{{ url_for('malware.upload') }}" class="btn btn-primary">Upload Malware Sample</a>
    </div>
{% endif %}
{% endblock %}
"""
    }
    
    # Create templates directory
    try:
        os.makedirs('templates', exist_ok=True)
        
        # Generate templates if they don't exist
        for template_name, template_content in templates.items():
            template_path = f'templates/{template_name}'
            if not os.path.exists(template_path):
                with open(template_path, 'w') as f:
                    f.write(template_content)
                logger.info(f"Created visualization template: {template_name}")
    except Exception as e:
        logger.error(f"Error generating templates: {e}")
