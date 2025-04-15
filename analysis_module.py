from flask import Blueprint, request, render_template, current_app, jsonify, flash, redirect, url_for
import pandas as pd
import numpy as np
import sqlite3
import os
import json
from datetime import datetime
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

# Create blueprint
analysis_bp = Blueprint('analysis', __name__, url_prefix='/analysis')

def init_app(app):
    """Initialize the analysis module with the Flask app"""
    app.register_blueprint(analysis_bp)

# Database schema
def create_database_schema(cursor):
    """Create database tables for the analysis module"""
    # Queries table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS analysis_queries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        dataset_id INTEGER,
        query_type TEXT NOT NULL,
        query_content TEXT NOT NULL,
        is_saved BOOLEAN DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (dataset_id) REFERENCES datasets(id)
    )
    ''')
    
    # Results table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS analysis_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        query_id INTEGER,
        result_type TEXT NOT NULL,
        result_data TEXT,
        row_count INTEGER,
        execution_time REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (query_id) REFERENCES analysis_queries(id)
    )
    ''')

# Routes
@analysis_bp.route('/')
def index():
    """Analysis module main page"""
    queries = get_saved_queries()
    return render_template('analysis_index.html', saved_queries=queries)

@analysis_bp.route('/create', methods=['GET', 'POST'])
def create():
    """Create and execute analysis queries"""
    # Get available datasets 
    from data_module import get_datasets
    datasets = get_datasets()
    
    if request.method == 'POST':
        name = request.form.get('name', 'Untitled Query')
        description = request.form.get('description', '')
        dataset_id = request.form.get('dataset_id', type=int)
        query_type = request.form.get('query_type', 'sql')
        query_content = request.form.get('query_content', '')
        is_saved = 'save_query' in request.form
        
        try:
            # Create the query
            query_id = create_query(name, description, dataset_id, query_type, query_content, is_saved)
            
            # Run if execute button was pressed
            if 'execute_query' in request.form:
                result_data, result_type, row_count, execution_time = execute_query(query_id)
                result_id = save_result(query_id, result_type, result_data, row_count, execution_time)
                flash(f'Query executed: {row_count} rows returned in {execution_time:.2f} seconds.', 'success')
                return redirect(url_for('analysis.view_result', result_id=result_id))
            
            flash('Query saved successfully.', 'success')
            return redirect(url_for('analysis.edit', query_id=query_id))
            
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
            return render_template('analysis_create.html', datasets=datasets, form_data=request.form)
    
    # GET request - show create form
    return render_template('analysis_create.html', datasets=datasets)

@analysis_bp.route('/edit/<int:query_id>', methods=['GET', 'POST'])
def edit(query_id):
    """Edit an analysis query"""
    query = get_query_by_id(query_id)
    if not query:
        flash('Query not found', 'error')
        return redirect(url_for('analysis.index'))
    
    from data_module import get_datasets
    datasets = get_datasets()
    
    if request.method == 'POST':
        name = request.form.get('name', 'Untitled Query')
        description = request.form.get('description', '')
        dataset_id = request.form.get('dataset_id', type=int)
        query_type = request.form.get('query_type', 'sql')
        query_content = request.form.get('query_content', '')
        is_saved = 'save_query' in request.form
        
        try:
            update_query(query_id, name, description, dataset_id, query_type, query_content, is_saved)
            
            if 'execute_query' in request.form:
                result_data, result_type, row_count, execution_time = execute_query(query_id)
                result_id = save_result(query_id, result_type, result_data, row_count, execution_time)
                flash(f'Query executed: {row_count} rows returned in {execution_time:.2f} seconds.', 'success')
                return redirect(url_for('analysis.view_result', result_id=result_id))
            
            flash('Query updated successfully.', 'success')
            return redirect(url_for('analysis.edit', query_id=query_id))
            
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
    
    return render_template('analysis_edit.html', query=query, datasets=datasets)

@analysis_bp.route('/result/<int:result_id>')
def view_result(result_id):
    """View analysis result"""
    result = get_result_by_id(result_id)
    if not result:
        flash('Result not found', 'error')
        return redirect(url_for('analysis.index'))
    
    query = get_query_by_id(result['query_id'])
    result_data = json.loads(result['result_data'])
    
    # Prepare data for display
    if result['result_type'] == 'dataframe' or result['result_type'] == 'aggregation':
        columns = list(result_data[0].keys()) if result_data else []
        display_data = {'type': 'table', 'columns': columns, 'records': result_data}
    else:
        display_data = {'type': 'raw', 'data': result_data}
    
    return render_template('analysis_result.html', result=result, query=query, display_data=display_data)

@analysis_bp.route('/delete/<int:query_id>', methods=['POST'])
def delete(query_id):
    """Delete an analysis query"""
    success = delete_query(query_id)
    flash('Query deleted successfully' if success else 'Error deleting query', 'success' if success else 'error')
    return redirect(url_for('analysis.index'))

@analysis_bp.route('/anomaly/<int:dataset_id>', methods=['GET', 'POST'])
def anomaly_detection(dataset_id):
    """Anomaly detection analysis"""
    from data_module import get_dataset_by_id, load_dataset, get_dataset_schema
    
    dataset = get_dataset_by_id(dataset_id)
    if not dataset:
        flash('Dataset not found', 'error')
        return redirect(url_for('analysis.index'))
    
    if request.method == 'POST':
        name = request.form.get('name', f'Anomaly Detection - {dataset["name"]}')
        description = request.form.get('description', 'Automated anomaly detection')
        features = request.form.getlist('features[]')
        contamination = float(request.form.get('contamination', 0.05))
        
        try:
            # Load the dataset
            df = load_dataset(dataset_id)
            
            # Run anomaly detection
            result_df, anomaly_count = run_anomaly_detection(df, features, contamination)
            
            # Create a record and save results
            query_id = create_query(
                name=name,
                description=description,
                dataset_id=dataset_id,
                query_type='anomaly_detection',
                query_content=json.dumps({'features': features, 'contamination': contamination}),
                is_saved=True
            )
            
            result_data = result_df.to_dict('records')
            result_id = save_result(query_id, 'dataframe', json.dumps(result_data), len(result_df), 0)
            
            flash(f'Anomaly detection completed: {anomaly_count} anomalies found out of {len(df)} records.', 'success')
            return redirect(url_for('analysis.view_result', result_id=result_id))
            
        except Exception as e:
            flash(f'Error performing anomaly detection: {str(e)}', 'error')
    
    # GET request - show form
    schema = get_dataset_schema(dataset_id)
    return render_template('analysis_anomaly.html', dataset=dataset, schema=schema)

# API endpoints
@analysis_bp.route('/api/queries')
def api_queries():
    """API endpoint to get all queries"""
    return jsonify(get_saved_queries())

@analysis_bp.route('/api/results/recent')
def api_recent_results():
    """API endpoint to get recent results"""
    limit = request.args.get('limit', 10, type=int)
    return jsonify(get_recent_results(limit))

# Analysis functions
def execute_query(query_id):
    """Execute a query and return results"""
    query = get_query_by_id(query_id)
    if not query:
        raise ValueError("Query not found")
    
    from data_module import get_dataset_by_id, load_dataset
    dataset = get_dataset_by_id(query['dataset_id'])
    if not dataset:
        raise ValueError("Dataset not found")
    
    start_time = datetime.now()
    
    if query['query_type'] == 'sql':
        # Execute SQL query
        result_df, row_count = execute_sql_query(query['query_content'], dataset)
        result_data = result_df.to_dict('records')
        result_type = 'dataframe'
        
    elif query['query_type'] == 'pattern':
        # Execute pattern matching
        pattern_spec = json.loads(query['query_content'])
        df = load_dataset(query['dataset_id'])
        filtered_df = df.copy()
        
        # Apply filters
        for filter_item in pattern_spec.get('filters', []):
            column, operator, value = filter_item.get('column'), filter_item.get('operator'), filter_item.get('value')
            if not all([column, operator, value]): continue
                
            if operator == 'contains':
                filtered_df = filtered_df[filtered_df[column].astype(str).str.contains(value, na=False)]
            elif operator == 'equals':
                filtered_df = filtered_df[filtered_df[column].astype(str) == value]
            elif operator == 'startswith':
                filtered_df = filtered_df[filtered_df[column].astype(str).str.startswith(value, na=False)]
            elif operator == 'endswith':
                filtered_df = filtered_df[filtered_df[column].astype(str).str.endswith(value, na=False)]
            elif operator == 'greater_than':
                filtered_df = filtered_df[pd.to_numeric(filtered_df[column], errors='coerce') > float(value)]
            elif operator == 'less_than':
                filtered_df = filtered_df[pd.to_numeric(filtered_df[column], errors='coerce') < float(value)]
                
        result_data = filtered_df.to_dict('records')
        result_type = 'dataframe'
        row_count = len(filtered_df)
        
    elif query['query_type'] == 'aggregation':
        # Execute aggregation
        agg_spec = json.loads(query['query_content'])
        df = load_dataset(query['dataset_id'])
        
        group_by = agg_spec.get('group_by', [])
        aggregations = agg_spec.get('aggregations', [])
        
        # Build aggregation dict
        agg_dict = {}
        for agg in aggregations:
            column, function = agg.get('column'), agg.get('function')
            if column and function:
                if column not in agg_dict:
                    agg_dict[column] = []
                agg_dict[column].append(function)
        
        # Perform aggregation
        if group_by:
            result_df = df.groupby(group_by).agg(agg_dict).reset_index()
        else:
            result_df = df.agg(agg_dict).reset_index()
        
        # Flatten column names if MultiIndex
        if isinstance(result_df.columns, pd.MultiIndex):
            result_df.columns = ['_'.join(col).strip() for col in result_df.columns.values]
        
        result_data = result_df.to_dict('records')
        result_type = 'aggregation'
        row_count = len(result_df)
    
    else:
        result_data = [{'message': f'Query type not implemented: {query["query_type"]}'}]
        result_type = 'message'
        row_count = 1
    
    execution_time = (datetime.now() - start_time).total_seconds()
    return result_data, result_type, row_count, execution_time

def execute_sql_query(query_content, dataset):
    """Execute a SQL query against a dataset"""
    conn = sqlite3.connect(current_app.config['DATABASE_PATH'])
    try:
        # Replace placeholders
        query_content = query_content.replace('{{table_name}}', dataset['table_name'])
        df = pd.read_sql_query(query_content, conn)
        return df, len(df)
    finally:
        conn.close()

def run_anomaly_detection(df, features, contamination=0.05):
    """Run anomaly detection using Isolation Forest"""
    # Validate features
    for feature in features:
        if feature not in df.columns:
            raise ValueError(f"Feature '{feature}' not found in dataset")
    
    # Extract and prepare features
    X = df[features].copy()
    for col in X.columns:
        if not pd.api.types.is_numeric_dtype(X[col]):
            X[col] = pd.to_numeric(X[col], errors='coerce')
    X = X.fillna(X.mean())
    
    # Standardize and run model
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    model = IsolationForest(contamination=contamination, random_state=42)
    
    # Add anomaly flags and scores
    df['anomaly'] = model.fit_predict(X_scaled)
    df['anomaly'] = df['anomaly'].map({1: 0, -1: 1})  # Convert to 0/1 flag
    df['anomaly_score'] = model.decision_function(X_scaled)
    # Convert to 0-1 scale (1 = most anomalous)
    df['anomaly_score'] = 1 - (df['anomaly_score'] - df['anomaly_score'].min()) / (df['anomaly_score'].max() - df['anomaly_score'].min())
    
    return df, df['anomaly'].sum()

# Database operations
def create_query(name, description, dataset_id, query_type, query_content, is_saved=False):
    """Create a new analysis query"""
    conn = sqlite3.connect(current_app.config['DATABASE_PATH'])
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            """
            INSERT INTO analysis_queries 
            (name, description, dataset_id, query_type, query_content, is_saved, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (name, description, dataset_id, query_type, query_content, is_saved)
        )
        
        query_id = cursor.lastrowid
        conn.commit()
        return query_id
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def update_query(query_id, name, description, dataset_id, query_type, query_content, is_saved=False):
    """Update an existing analysis query"""
    conn = sqlite3.connect(current_app.config['DATABASE_PATH'])
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            """
            UPDATE analysis_queries 
            SET name = ?, description = ?, dataset_id = ?, query_type = ?, 
                query_content = ?, is_saved = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (name, description, dataset_id, query_type, query_content, is_saved, query_id)
        )
        
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def save_result(query_id, result_type, result_data, row_count, execution_time):
    """Save analysis result"""
    conn = sqlite3.connect(current_app.config['DATABASE_PATH'])
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            """
            INSERT INTO analysis_results 
            (query_id, result_type, result_data, row_count, execution_time, created_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (query_id, result_type, result_data, row_count, execution_time)
        )
        
        result_id = cursor.lastrowid
        conn.commit()
        return result_id
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_query_by_id(query_id):
    """Get query information by ID"""
    conn = sqlite3.connect(current_app.config['DATABASE_PATH'])
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM analysis_queries WHERE id = ?", (query_id,))
    query = cursor.fetchone()
    
    conn.close()
    return dict(query) if query else None

def get_saved_queries():
    """Get a list of all saved queries"""
    conn = sqlite3.connect(current_app.config['DATABASE_PATH'])
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT q.*, d.name as dataset_name 
        FROM analysis_queries q
        LEFT JOIN datasets d ON q.dataset_id = d.id
        WHERE q.is_saved = 1
        ORDER BY q.updated_at DESC
    """)
    queries = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return queries

def get_result_by_id(result_id):
    """Get result information by ID"""
    conn = sqlite3.connect(current_app.config['DATABASE_PATH'])
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM analysis_results WHERE id = ?", (result_id,))
    result = cursor.fetchone()
    
    conn.close()
    return dict(result) if result else None

def get_recent_results(limit=10):
    """Get recent analysis results"""
    conn = sqlite3.connect(current_app.config['DATABASE_PATH'])
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT r.*, q.name as query_name
        FROM analysis_results r
        JOIN analysis_queries q ON r.query_id = q.id
        ORDER BY r.created_at DESC
        LIMIT ?
    """, (limit,))
    results = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return results

def delete_query(query_id):
    """Delete a query and its results"""
    conn = sqlite3.connect(current_app.config['DATABASE_PATH'])
    cursor = conn.cursor()
    
    try:
        # Delete related results
        cursor.execute("DELETE FROM analysis_results WHERE query_id = ?", (query_id,))
        # Delete the query
        cursor.execute("DELETE FROM analysis_queries WHERE id = ?", (query_id,))
        
        conn.commit()
        return True
    except:
        conn.rollback()
        return False
    finally:
        conn.close()

# Template and static file generation
def generate_css():
    """Generate minimal CSS for the analysis module"""
    css = """
    /* Analysis Module CSS */
    .query-editor { font-family: monospace; min-height: 200px; }
    .sql-keyword { color: #0066cc; font-weight: bold; }
    .result-table { width: 100%; overflow-x: auto; }
    .result-table table { width: 100%; border-collapse: collapse; }
    .result-table th, .result-table td { padding: 8px; border: 1px solid #ddd; }
    .result-table th { background-color: #f5f5f5; position: sticky; top: 0; }
    .query-actions { display: flex; gap: 10px; margin-top: 15px; }
    .severity-low { color: #28a745; }
    .severity-medium { color: #ffc107; }
    .severity-high { color: #fd7e14; }
    .severity-critical { color: #dc3545; }
    """
    
    os.makedirs('static/css', exist_ok=True)
    with open('static/css/analysis_module.css', 'w') as f:
        f.write(css)

def generate_js():
    """Generate minimal JavaScript for the analysis module"""
    js = """
    // Analysis Module JavaScript
    document.addEventListener('DOMContentLoaded', function() {
        // Handle query type change
        const queryTypeSelect = document.getElementById('query-type');
        const editors = {
            'sql': document.getElementById('sql-editor'),
            'pattern': document.getElementById('pattern-editor'),
            'aggregation': document.getElementById('aggregation-editor'),
            'custom': document.getElementById('custom-editor')
        };
        
        if (queryTypeSelect) {
            // Hide all editors initially except the first one
            Object.values(editors).forEach(editor => {
                if (editor) editor.style.display = 'none';
            });
            if (editors.sql) editors.sql.style.display = 'block';
            
            // Change editor based on selected query type
            queryTypeSelect.addEventListener('change', function() {
                const selectedType = this.value;
                Object.entries(editors).forEach(([type, editor]) => {
                    if (editor) editor.style.display = type === selectedType ? 'block' : 'none';
                });
            });
        }
        
        // Handle delete confirmation
        document.querySelectorAll('.delete-query-btn').forEach(button => {
            button.addEventListener('click', function(e) {
                if (!confirm('Are you sure you want to delete this query?')) {
                    e.preventDefault();
                }
            });
        });
        
        // Handle result table search
        const searchInput = document.getElementById('result-search');
        const resultTable = document.querySelector('.result-table table');
        if (searchInput && resultTable) {
            searchInput.addEventListener('keyup', function() {
                const searchTerm = this.value.toLowerCase();
                resultTable.querySelectorAll('tbody tr').forEach(row => {
                    row.style.display = row.textContent.toLowerCase().includes(searchTerm) ? '' : 'none';
                });
            });
        }
    });
    """
    
    os.makedirs('static/js', exist_ok=True)
    with open('static/js/analysis_module.js', 'w') as f:
        f.write(js)

def generate_templates():
    """Generate basic templates for the analysis module"""
    # Just create essential templates
    os.makedirs('templates', exist_ok=True)
    
    # Templates will be generated when needed
    # This is a placeholder to match the interface expected by main.py
    pass
