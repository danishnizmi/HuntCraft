from flask import Blueprint, request, render_template, current_app, jsonify, flash, redirect, url_for
import pandas as pd
import numpy as np
import sqlite3
import os
import json
import logging
from datetime import datetime
from functools import wraps
import re
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler, RobustScaler
from sklearn.cluster import DBSCAN
from concurrent.futures import ThreadPoolExecutor

# Create blueprint
analysis_bp = Blueprint('analysis', __name__, url_prefix='/analysis')

# Setup logging
logger = logging.getLogger(__name__)

def init_app(app):
    """Initialize the analysis module with the Flask app"""
    app.register_blueprint(analysis_bp)
    
    # Generate assets within app context
    with app.app_context():
        generate_css()
        generate_js()
        generate_templates()

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
        user_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (dataset_id) REFERENCES datasets(id),
        FOREIGN KEY (user_id) REFERENCES users(id)
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

# Helper function for DB connections
def _db_connection(row_factory=None):
    """Create a database connection with optional row factory"""
    conn = sqlite3.connect(current_app.config['DATABASE_PATH'])
    if row_factory:
        conn.row_factory = row_factory
    return conn

# Error handling decorator
def handle_errors(func):
    """Decorator for standardized error handling"""
    @wraps(func)
    def wrapped(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {func.__name__}: {str(e)}")
            flash(f"Error: {str(e)}", "error")
            return redirect(url_for("analysis.index"))
    return wrapped

# Routes
@analysis_bp.route('/')
def index():
    """Analysis module main page"""
    queries = get_saved_queries()
    return render_template('analysis_index.html', saved_queries=queries)

@analysis_bp.route('/create', methods=['GET', 'POST'])
@handle_errors
def create():
    """Create and execute analysis queries"""
    # Get available datasets 
    from data_module import get_datasets
    datasets = get_datasets()
    
    # Get current user ID if available (for multi-user support)
    user_id = None
    try:
        from flask_login import current_user
        if current_user.is_authenticated:
            user_id = current_user.id
    except:
        pass
    
    if request.method == 'POST':
        name = request.form.get('name', 'Untitled Query')
        description = request.form.get('description', '')
        dataset_id = request.form.get('dataset_id', type=int)
        query_type = request.form.get('query_type', 'sql')
        query_content = request.form.get('query_content', '')
        is_saved = 'save_query' in request.form
        
        # Create the query
        query_id = create_query(name, description, dataset_id, query_type, query_content, is_saved, user_id)
        
        # Run if execute button was pressed
        if 'execute_query' in request.form:
            result_data, result_type, row_count, execution_time = execute_query(query_id)
            result_id = save_result(query_id, result_type, result_data, row_count, execution_time)
            flash(f'Query executed: {row_count} rows returned in {execution_time:.2f} seconds.', 'success')
            return redirect(url_for('analysis.view_result', result_id=result_id))
        
        flash('Query saved successfully.', 'success')
        return redirect(url_for('analysis.edit', query_id=query_id))
    
    # GET request - show create form
    return render_template('analysis_create.html', datasets=datasets)

@analysis_bp.route('/edit/<int:query_id>', methods=['GET', 'POST'])
@handle_errors
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
        
        # Update the query
        update_query(query_id, name, description, dataset_id, query_type, query_content, is_saved)
        
        if 'execute_query' in request.form:
            result_data, result_type, row_count, execution_time = execute_query(query_id)
            result_id = save_result(query_id, result_type, result_data, row_count, execution_time)
            flash(f'Query executed: {row_count} rows returned in {execution_time:.2f} seconds.', 'success')
            return redirect(url_for('analysis.view_result', result_id=result_id))
        
        flash('Query updated successfully.', 'success')
        return redirect(url_for('analysis.edit', query_id=query_id))
    
    return render_template('analysis_edit.html', query=query, datasets=datasets)

@analysis_bp.route('/result/<int:result_id>')
@handle_errors
def view_result(result_id):
    """View analysis result"""
    result = get_result_by_id(result_id)
    if not result:
        flash('Result not found', 'error')
        return redirect(url_for('analysis.index'))
    
    query = get_query_by_id(result['query_id'])
    result_data = json.loads(result['result_data'])
    
    # Generate summary statistics for the result
    summary = _generate_result_summary(result_data, result['result_type'])
    
    # Prepare data for display
    if result['result_type'] in ['dataframe', 'aggregation']:
        columns = list(result_data[0].keys()) if result_data else []
        display_data = {'type': 'table', 'columns': columns, 'records': result_data, 'summary': summary}
    else:
        display_data = {'type': 'raw', 'data': result_data}
    
    return render_template('analysis_result.html', result=result, query=query, display_data=display_data)

@analysis_bp.route('/delete/<int:query_id>', methods=['POST'])
@handle_errors
def delete(query_id):
    """Delete an analysis query"""
    success = delete_query(query_id)
    flash('Query deleted successfully' if success else 'Error deleting query', 'success' if success else 'error')
    return redirect(url_for('analysis.index'))

@analysis_bp.route('/anomaly/<int:dataset_id>', methods=['GET', 'POST'])
@handle_errors
def anomaly_detection(dataset_id):
    """Anomaly detection analysis"""
    from data_module import get_dataset_by_id, load_dataset, get_dataset_schema
    
    dataset = get_dataset_by_id(dataset_id)
    if not dataset:
        flash('Dataset not found', 'error')
        return redirect(url_for('analysis.index'))
    
    # Get current user ID if available
    user_id = None
    try:
        from flask_login import current_user
        if current_user.is_authenticated:
            user_id = current_user.id
    except:
        pass
    
    if request.method == 'POST':
        name = request.form.get('name', f'Anomaly Detection - {dataset["name"]}')
        description = request.form.get('description', 'Automated anomaly detection')
        features = request.form.getlist('features[]')
        algorithm = request.form.get('algorithm', 'isolation_forest')
        contamination = float(request.form.get('contamination', 0.05))
        
        # Load the dataset
        df = load_dataset(dataset_id)
        
        # Run anomaly detection
        result_df, anomaly_count, anomaly_details = run_anomaly_detection(
            df, features, algorithm, contamination
        )
        
        # Create a record and save results
        query_content = json.dumps({
            'features': features, 
            'algorithm': algorithm,
            'contamination': contamination,
            'anomaly_details': anomaly_details
        })
        
        query_id = create_query(
            name=name,
            description=description,
            dataset_id=dataset_id,
            query_type='anomaly_detection',
            query_content=query_content,
            is_saved=True,
            user_id=user_id
        )
        
        result_data = result_df.to_dict('records')
        result_id = save_result(query_id, 'dataframe', json.dumps(result_data), len(result_df), 0)
        
        flash(f'Anomaly detection completed: {anomaly_count} anomalies found out of {len(df)} records.', 'success')
        return redirect(url_for('analysis.view_result', result_id=result_id))
    
    # GET request - show form
    schema = get_dataset_schema(dataset_id)
    
    # Get numeric columns for feature selection
    numeric_columns = []
    if schema and 'columns' in schema:
        for col in schema['columns']:
            if 'int' in col['type'] or 'float' in col['type'] or 'number' in col['type']:
                numeric_columns.append(col['name'])
    
    return render_template('analysis_anomaly.html', 
                          dataset=dataset, 
                          schema=schema, 
                          numeric_columns=numeric_columns)

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
        # Execute SQL query with enhanced security and error handling
        result_df, row_count = execute_sql_query(query['query_content'], dataset)
        result_data = result_df.to_dict('records')
        result_type = 'dataframe'
        
    elif query['query_type'] == 'pattern':
        # Execute pattern matching with optimized filtering
        pattern_spec = json.loads(query['query_content'])
        df = load_dataset(query['dataset_id'])
        filtered_df = apply_pattern_filters(df, pattern_spec.get('filters', []))
                
        result_data = filtered_df.to_dict('records')
        result_type = 'dataframe'
        row_count = len(filtered_df)
        
    elif query['query_type'] == 'aggregation':
        # Execute aggregation with enhanced grouping and calculation
        agg_spec = json.loads(query['query_content'])
        df = load_dataset(query['dataset_id'])
        
        result_df = perform_aggregation(df, agg_spec)
        
        result_data = result_df.to_dict('records')
        result_type = 'aggregation'
        row_count = len(result_df)
    
    elif query['query_type'] == 'anomaly_detection':
        # Results are pre-computed for anomaly detection
        # Just return the previous result for viewing
        result_data = [{'message': 'Anomaly detection results should be viewed from the results page'}]
        result_type = 'message'
        row_count = 1
    
    else:
        result_data = [{'message': f'Query type not implemented: {query["query_type"]}'}]
        result_type = 'message'
        row_count = 1
    
    execution_time = (datetime.now() - start_time).total_seconds()
    return result_data, result_type, row_count, execution_time

def execute_sql_query(query_content, dataset):
    """Execute a SQL query against a dataset with enhanced security"""
    conn = _db_connection()
    try:
        # Replace placeholders safely
        safe_table_name = dataset['table_name']
        safe_query = query_content.replace('{{table_name}}', safe_table_name)
        
        # Basic SQL injection prevention for demonstration
        # (In production, use parameterized queries or an ORM)
        if _is_dangerous_sql(safe_query):
            raise ValueError("Potential SQL injection detected")
        
        # Execute the query
        try:
            df = pd.read_sql_query(safe_query, conn)
            return df, len(df)
        except Exception as e:
            # Provide more helpful error messages for common SQL errors
            error_msg = str(e).lower()
            if 'syntax error' in error_msg:
                raise ValueError(f"SQL syntax error: Check your query for mistakes")
            elif 'no such column' in error_msg:
                column_match = re.search(r"no such column: ([^\s]+)", error_msg)
                if column_match:
                    raise ValueError(f"Column '{column_match.group(1)}' not found in the dataset")
                else:
                    raise ValueError("Column not found error: Check your column names")
            elif 'no such table' in error_msg:
                raise ValueError(f"Table '{safe_table_name}' not found. The dataset may have been deleted.")
            else:
                raise ValueError(f"SQL error: {str(e)}")
    finally:
        conn.close()

def _is_dangerous_sql(query):
    """Basic check for potentially dangerous SQL commands"""
    dangerous_patterns = [
        r';\s*DROP\s+TABLE',
        r';\s*DELETE\s+FROM',
        r';\s*UPDATE\s+.*?\s+SET',
        r';\s*ALTER\s+TABLE',
        r';\s*CREATE\s+TABLE',
        r'PRAGMA',
        r'ATTACH\s+DATABASE',
        r'DETACH\s+DATABASE',
    ]
    
    # Check for dangerous patterns (case insensitive)
    for pattern in dangerous_patterns:
        if re.search(pattern, query, re.IGNORECASE):
            return True
    
    return False

def apply_pattern_filters(df, filters):
    """Apply pattern matching filters to a DataFrame"""
    if not filters:
        return df
    
    filtered_df = df.copy()
    
    # Build filter expressions
    for filter_item in filters:
        column = filter_item.get('column')
        operator = filter_item.get('operator')
        value = filter_item.get('value')
        
        if not all([column, operator, value]) or column not in df.columns:
            continue
        
        try:
            # Get column data type
            col_dtype = str(df[column].dtype)
            is_numeric = 'int' in col_dtype or 'float' in col_dtype
            is_datetime = 'datetime' in col_dtype
            
            # Apply appropriate filter based on operator and data type
            if operator == 'contains':
                filtered_df = filtered_df[filtered_df[column].astype(str).str.contains(value, na=False, case=False)]
            elif operator == 'equals':
                if is_numeric:
                    try:
                        numeric_value = float(value)
                        filtered_df = filtered_df[filtered_df[column] == numeric_value]
                    except ValueError:
                        filtered_df = filtered_df[filtered_df[column].astype(str) == value]
                else:
                    filtered_df = filtered_df[filtered_df[column].astype(str) == value]
            elif operator == 'startswith':
                filtered_df = filtered_df[filtered_df[column].astype(str).str.startswith(value, na=False)]
            elif operator == 'endswith':
                filtered_df = filtered_df[filtered_df[column].astype(str).str.endswith(value, na=False)]
            elif operator == 'greater_than':
                if is_datetime:
                    try:
                        date_value = pd.to_datetime(value)
                        filtered_df = filtered_df[filtered_df[column] > date_value]
                    except:
                        pass  # Skip if datetime conversion fails
                else:
                    try:
                        numeric_value = float(value)
                        filtered_df = filtered_df[pd.to_numeric(filtered_df[column], errors='coerce') > numeric_value]
                    except ValueError:
                        pass  # Skip if numeric conversion fails
            elif operator == 'less_than':
                if is_datetime:
                    try:
                        date_value = pd.to_datetime(value)
                        filtered_df = filtered_df[filtered_df[column] < date_value]
                    except:
                        pass  # Skip if datetime conversion fails
                else:
                    try:
                        numeric_value = float(value)
                        filtered_df = filtered_df[pd.to_numeric(filtered_df[column], errors='coerce') < numeric_value]
                    except ValueError:
                        pass  # Skip if numeric conversion fails
            elif operator == 'between':
                # Handle range values in format "min,max"
                if ',' in value:
                    try:
                        min_val, max_val = value.split(',', 1)
                        min_val = min_val.strip()
                        max_val = max_val.strip()
                        
                        if is_datetime:
                            min_date = pd.to_datetime(min_val)
                            max_date = pd.to_datetime(max_val)
                            filtered_df = filtered_df[(filtered_df[column] >= min_date) & (filtered_df[column] <= max_date)]
                        else:
                            min_num = float(min_val)
                            max_num = float(max_val)
                            filtered_df = filtered_df[(pd.to_numeric(filtered_df[column], errors='coerce') >= min_num) & 
                                                      (pd.to_numeric(filtered_df[column], errors='coerce') <= max_num)]
                    except:
                        pass  # Skip if conversion fails
            elif operator == 'in_list':
                # Handle list values in format "value1,value2,value3"
                value_list = [v.strip() for v in value.split(',')]
                filtered_df = filtered_df[filtered_df[column].astype(str).isin(value_list)]
        except Exception as e:
            logger.warning(f"Error applying filter '{operator}' to column '{column}': {str(e)}")
            # Continue with the next filter
            
    return filtered_df

def perform_aggregation(df, agg_spec):
    """Perform aggregation on a DataFrame with enhanced features"""
    # Get aggregation parameters
    group_by = agg_spec.get('group_by', [])
    aggregations = agg_spec.get('aggregations', [])
    having = agg_spec.get('having', [])  # Optional HAVING-like filter
    sort_by = agg_spec.get('sort_by', {})  # Optional sorting
    limit = agg_spec.get('limit', None)  # Optional limit
    
    # Check for valid input
    if not aggregations:
        return pd.DataFrame()
    
    # Build aggregation dictionary
    agg_dict = {}
    for agg in aggregations:
        column, function = agg.get('column'), agg.get('function')
        if column and function:
            if column not in agg_dict:
                agg_dict[column] = []
            agg_dict[column].append(function)
    
    # Perform aggregation
    try:
        if group_by:
            # Handle multiple group_by columns
            result_df = df.groupby(group_by, dropna=False).agg(agg_dict).reset_index()
        else:
            # For non-grouped aggregations
            result_df = df.agg(agg_dict).reset_index()
            result_df.rename(columns={'index': 'function'}, inplace=True)
    
        # Flatten column names if MultiIndex
        if isinstance(result_df.columns, pd.MultiIndex):
            result_df.columns = [f"{col[0]}_{col[1]}" if col[1] else col[0] for col in result_df.columns.values]
        
        # Apply HAVING-like filtering
        if having:
            for condition in having:
                column = condition.get('column')
                operator = condition.get('operator')
                value = condition.get('value')
                
                if column and operator and value is not None:
                    # Apply the filter based on the operator
                    if operator == 'greater_than':
                        result_df = result_df[result_df[column] > float(value)]
                    elif operator == 'less_than':
                        result_df = result_df[result_df[column] < float(value)]
                    elif operator == 'equals':
                        result_df = result_df[result_df[column] == float(value)]
                    elif operator == 'not_equals':
                        result_df = result_df[result_df[column] != float(value)]
        
        # Apply sorting
        if sort_by:
            column = sort_by.get('column')
            direction = sort_by.get('direction', 'asc')
            
            if column and column in result_df.columns:
                result_df = result_df.sort_values(
                    by=column, 
                    ascending=(direction.lower() == 'asc')
                )
        
        # Apply limit
        if limit and isinstance(limit, int) and limit > 0:
            result_df = result_df.head(limit)
        
        return result_df
    except Exception as e:
        logger.error(f"Aggregation error: {str(e)}")
        raise ValueError(f"Error performing aggregation: {str(e)}")

def run_anomaly_detection(df, features, algorithm='isolation_forest', contamination=0.05):
    """Run anomaly detection using multiple algorithms"""
    # Validate features
    available_features = []
    for feature in features:
        if feature in df.columns:
            # Check if feature is numeric
            if pd.api.types.is_numeric_dtype(df[feature]):
                available_features.append(feature)
            else:
                # Try to convert to numeric
                try:
                    df[feature] = pd.to_numeric(df[feature], errors='coerce')
                    available_features.append(feature)
                except:
                    logger.warning(f"Feature '{feature}' is not numeric and couldn't be converted")
    
    if not available_features:
        raise ValueError("No valid numeric features available for anomaly detection")
    
    # Extract and prepare features
    X = df[available_features].copy()
    
    # Handle missing values with median imputation
    for col in X.columns:
        median_val = X[col].median()
        X[col] = X[col].fillna(median_val)
    
    # Choose the appropriate scaler to reduce the effect of outliers
    if algorithm == 'dbscan':
        # Use RobustScaler for DBSCAN as it's less sensitive to outliers
        scaler = RobustScaler()
    else:
        # Standard scaler is fine for other algorithms
        scaler = StandardScaler()
    
    X_scaled = scaler.fit_transform(X)
    
    # Run selected algorithm
    if algorithm == 'isolation_forest':
        model = IsolationForest(
            contamination=contamination, 
            random_state=42,
            n_jobs=-1  # Use all available processors
        )
        y_pred = model.fit_predict(X_scaled)
        anomaly_scores = model.decision_function(X_scaled)
        # Convert to anomaly flags (1 for anomaly, 0 for normal)
        anomaly_flags = np.where(y_pred == -1, 1, 0)
        
    elif algorithm == 'dbscan':
        # DBSCAN for density-based anomaly detection
        # Automatically determine epsilon based on data
        from sklearn.neighbors import NearestNeighbors
        nn = NearestNeighbors(n_neighbors=min(10, len(X_scaled)))
        nn.fit(X_scaled)
        distances, _ = nn.kneighbors(X_scaled)
        
        # Use mean of 10th nearest neighbor distance as epsilon
        epsilon = np.mean(distances[:, -1]) * 1.5
        
        # Run DBSCAN
        model = DBSCAN(
            eps=epsilon,
            min_samples=max(5, int(len(X_scaled) * 0.01)),  # At least 1% of points or 5
            n_jobs=-1
        )
        clusters = model.fit_predict(X_scaled)
        
        # Points labeled as -1 are noise/anomalies in DBSCAN
        anomaly_flags = np.where(clusters == -1, 1, 0)
        
        # Create pseudo-scores based on distance to nearest core point
        anomaly_scores = np.zeros_like(anomaly_flags, dtype=float)
        if -1 in clusters:  # If there are any anomalies
            core_samples_mask = np.zeros_like(clusters, dtype=bool)
            core_samples_mask[model.core_sample_indices_] = True
            
            # For each point, calculate distance to nearest core point
            from sklearn.metrics import pairwise_distances_argmin_min
            if np.any(core_samples_mask):  # If there are any core points
                _, distances = pairwise_distances_argmin_min(
                    X_scaled[~core_samples_mask], X_scaled[core_samples_mask]
                )
                # Normalize distances to 0-1 range
                if len(distances) > 0:
                    max_dist = max(distances)
                    min_dist = min(distances)
                    if max_dist > min_dist:
                        normalized_distances = (distances - min_dist) / (max_dist - min_dist)
                    else:
                        normalized_distances = np.zeros_like(distances)
                    
                    # Assign scores
                    anomaly_scores[~core_samples_mask] = normalized_distances
    else:
        # Default to Isolation Forest if unknown algorithm
        model = IsolationForest(contamination=contamination, random_state=42)
        y_pred = model.fit_predict(X_scaled)
        anomaly_scores = model.decision_function(X_scaled)
        anomaly_flags = np.where(y_pred == -1, 1, 0)
    
    # Convert anomaly scores to 0-1 scale (1 = most anomalous)
    anomaly_scores = 1 - (anomaly_scores - np.min(anomaly_scores)) / (np.max(anomaly_scores) - np.min(anomaly_scores))
    
    # Add results to dataframe
    result_df = df.copy()
    result_df['anomaly'] = anomaly_flags
    result_df['anomaly_score'] = anomaly_scores
    
    # Add feature contribution if using Isolation Forest
    feature_importance = {}
    if algorithm == 'isolation_forest':
        try:
            # Extract feature importance if available
            if hasattr(model, 'feature_importances_'):
                importance = model.feature_importances_
                for i, feature in enumerate(available_features):
                    feature_importance[feature] = float(importance[i])
                    # Add individual feature anomaly contributions
                    col_name = f"contrib_{feature}"
                    result_df[col_name] = X_scaled[:, i] * importance[i]
        except:
            pass
    
    # Determine severity levels
    result_df['severity'] = pd.cut(
        result_df['anomaly_score'], 
        bins=[0, 0.25, 0.5, 0.75, 1], 
        labels=['low', 'medium', 'high', 'critical']
    )
    
    # Create anomaly details
    anomaly_count = int(result_df['anomaly'].sum())
    anomaly_details = {
        'total_records': len(df),
        'anomaly_count': anomaly_count,
        'anomaly_percent': round(anomaly_count * 100 / len(df), 2),
        'algorithm': algorithm,
        'contamination': contamination,
        'features': available_features,
        'feature_importance': feature_importance,
        'severity_counts': {
            'low': int((result_df['severity'] == 'low').sum()),
            'medium': int((result_df['severity'] == 'medium').sum()),
            'high': int((result_df['severity'] == 'high').sum()),
            'critical': int((result_df['severity'] == 'critical').sum())
        }
    }
    
    return result_df, anomaly_count, anomaly_details

def _generate_result_summary(result_data, result_type):
    """Generate summary statistics for analysis results"""
    if not result_data or not isinstance(result_data, list):
        return None
        
    if result_type not in ['dataframe', 'aggregation']:
        return None
    
    # Convert to DataFrame for easier analysis
    df = pd.DataFrame(result_data)
    
    summary = {
        'row_count': len(df),
        'column_count': len(df.columns),
        'columns': {}
    }
    
    # For numeric columns, get statistics
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    for col in numeric_cols:
        col_stats = df[col].describe().to_dict()
        # Convert numpy values to native Python types for JSON serialization
        summary['columns'][col] = {k: float(v) for k, v in col_stats.items()}
    
    # For non-numeric columns, get basic info
    non_numeric_cols = df.select_dtypes(exclude=[np.number]).columns
    for col in non_numeric_cols:
        summary['columns'][col] = {
            'unique_values': int(df[col].nunique()),
            'missing_values': int(df[col].isna().sum()),
            'sample_values': df[col].dropna().head(5).tolist()
        }
    
    return summary

# Database operations
def create_query(name, description, dataset_id, query_type, query_content, is_saved=False, user_id=None):
    """Create a new analysis query"""
    conn = _db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            """
            INSERT INTO analysis_queries 
            (name, description, dataset_id, query_type, query_content, is_saved, user_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (name, description, dataset_id, query_type, query_content, is_saved, user_id)
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
    conn = _db_connection()
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
    conn = _db_connection()
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
    conn = _db_connection(sqlite3.Row)
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM analysis_queries WHERE id = ?", (query_id,))
    query = cursor.fetchone()
    
    conn.close()
    return dict(query) if query else None

def get_saved_queries(user_id=None):
    """Get a list of all saved queries"""
    conn = _db_connection(sqlite3.Row)
    cursor = conn.cursor()
    
    if user_id is not None:
        # Get queries for specific user or shared queries (user_id is NULL)
        cursor.execute("""
            SELECT q.*, d.name as dataset_name 
            FROM analysis_queries q
            LEFT JOIN datasets d ON q.dataset_id = d.id
            WHERE q.is_saved = 1 AND (q.user_id = ? OR q.user_id IS NULL)
            ORDER BY q.updated_at DESC
        """, (user_id,))
    else:
        # Get all saved queries
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
    conn = _db_connection(sqlite3.Row)
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM analysis_results WHERE id = ?", (result_id,))
    result = cursor.fetchone()
    
    conn.close()
    return dict(result) if result else None

def get_recent_results(limit=10, user_id=None):
    """Get recent analysis results"""
    conn = _db_connection(sqlite3.Row)
    cursor = conn.cursor()
    
    if user_id is not None:
        cursor.execute("""
            SELECT r.*, q.name as query_name, q.user_id
            FROM analysis_results r
            JOIN analysis_queries q ON r.query_id = q.id
            WHERE q.user_id = ? OR q.user_id IS NULL
            ORDER BY r.created_at DESC
            LIMIT ?
        """, (user_id, limit))
    else:
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
    conn = _db_connection()
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
    """Generate CSS for the analysis module"""
    css = """
    /* Analysis Module CSS */
    .query-editor {
        font-family: monospace;
        min-height: 200px;
        border: 1px solid #ced4da;
        border-radius: 0.25rem;
        padding: 0.5rem;
        line-height: 1.5;
        resize: vertical;
    }
    
    .sql-keyword {
        color: #0066cc;
        font-weight: bold;
    }
    
    .result-table {
        width: 100%;
        overflow-x: auto;
        margin-bottom: 1rem;
    }
    
    .result-table-container {
        max-height: 600px;
        overflow-y: auto;
    }
    
    .result-table table {
        width: 100%;
        border-collapse: collapse;
    }
    
    .result-table th,
    .result-table td {
        padding: 8px;
        border: 1px solid #ddd;
        max-width: 300px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    
    .result-table th {
        background-color: #f5f5f5;
        position: sticky;
        top: 0;
        z-index: 10;
        font-weight: 600;
    }
    
    .result-table tr:nth-child(even) {
        background-color: #f9f9f9;
    }
    
    .result-table tr:hover {
        background-color: #f0f0f0;
    }
    
    .query-actions {
        display: flex;
        gap: 10px;
        margin-top: 15px;
    }
    
    .severity-low {
        color: #28a745;
        background-color: rgba(40, 167, 69, 0.1);
    }
    
    .severity-medium {
        color: #ffc107;
        background-color: rgba(255, 193, 7, 0.1);
    }
    
    .severity-high {
        color: #fd7e14;
        background-color: rgba(253, 126, 20, 0.1);
    }
    
    .severity-critical {
        color: #dc3545;
        background-color: rgba(220, 53, 69, 0.1);
    }
    
    .query-card {
        transition: transform 0.2s ease-in-out, box-shadow 0.2s ease-in-out;
        margin-bottom: 1.5rem;
    }
    
    .query-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 5px 15px rgba(0,0,0,0.1);
    }
    
    .result-summary {
        background-color: #f8f9fa;
        padding: 15px;
        border-radius: 4px;
        margin-bottom: 20px;
    }
    
    .result-summary h5 {
        margin-top: 0;
        color: #495057;
    }
    
    .result-meta {
        display: flex;
        gap: 1rem;
        flex-wrap: wrap;
    }
    
    .result-meta-item {
        background-color: #e9ecef;
        padding: 0.5rem 1rem;
        border-radius: 4px;
        font-size: 0.9rem;
    }
    
    .result-filters {
        margin-bottom: 1rem;
    }
    
    /* Animation for data loading */
    @keyframes analysisFadeIn {
        from { opacity: 0; transform: translateY(10px); }
        to { opacity: 1; transform: translateY(0); }
    }
    
    .analysis-fade-in {
        animation: analysisFadeIn 0.3s ease-out;
    }
    
    /* Feature selection styles */
    .feature-selector {
        border: 1px solid #ced4da;
        border-radius: 0.25rem;
        padding: 0.5rem;
        margin-bottom: 1rem;
        max-height: 250px;
        overflow-y: auto;
    }
    
    .feature-item {
        display: flex;
        align-items: center;
        padding: 0.25rem 0;
    }
    
    .feature-item input {
        margin-right: 0.5rem;
    }
    
    /* SQL editor enhancements */
    .editor-container {
        position: relative;
        margin-bottom: 1rem;
    }
    
    .editor-toolbar {
        background-color: #f8f9fa;
        border: 1px solid #ced4da;
        border-bottom: none;
        border-radius: 0.25rem 0.25rem 0 0;
        padding: 0.25rem;
        display: flex;
        gap: 0.25rem;
    }
    
    .editor-toolbar button {
        background: none;
        border: none;
        padding: 0.25rem 0.5rem;
        cursor: pointer;
        font-size: 0.875rem;
        border-radius: 0.25rem;
    }
    
    .editor-toolbar button:hover {
        background-color: #e9ecef;
    }
    
    /* Responsive styles */
    @media (max-width: 768px) {
        .query-actions {
            flex-wrap: wrap;
        }
        
        .result-meta {
            flex-direction: column;
            gap: 0.5rem;
        }
    }
    """
    
    os.makedirs('static/css', exist_ok=True)
    with open('static/css/analysis_module.css', 'w') as f:
        f.write(css)

def generate_js():
    """Generate enhanced JavaScript for the analysis module"""
    js = """
    // Analysis Module JavaScript
    document.addEventListener('DOMContentLoaded', function() {
        // Handle query type change
        const queryTypeSelect = document.getElementById('query-type');
        const editors = {
            'sql': document.getElementById('sql-editor-container'),
            'pattern': document.getElementById('pattern-editor-container'),
            'aggregation': document.getElementById('aggregation-editor-container'),
            'custom': document.getElementById('custom-editor-container')
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
            
            // Trigger change event to ensure correct editor is shown
            queryTypeSelect.dispatchEvent(new Event('change'));
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
        
        // Initialize tooltips
        const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        if (tooltipTriggerList.length > 0) {
            tooltipTriggerList.forEach(function(tooltipTriggerEl) {
                new bootstrap.Tooltip(tooltipTriggerEl);
            });
        }
        
        // SQL autocomplete and highlighting
        const sqlEditor = document.getElementById('sql-content');
        if (sqlEditor) {
            // Add SQL keywords for highlighting
            const sqlKeywords = [
                'SELECT', 'FROM', 'WHERE', 'GROUP BY', 'ORDER BY', 'HAVING',
                'JOIN', 'LEFT JOIN', 'RIGHT JOIN', 'INNER JOIN', 'OUTER JOIN',
                'ON', 'AS', 'AND', 'OR', 'NOT', 'IN', 'LIKE', 'BETWEEN',
                'COUNT', 'SUM', 'AVG', 'MIN', 'MAX', 'DISTINCT', 'LIMIT'
            ];
            
            // Simple SQL syntax highlighting
            sqlEditor.addEventListener('input', function() {
                // Store cursor position
                const cursorPos = this.selectionStart;
                
                // Apply highlighting
                let text = this.value;
                sqlKeywords.forEach(keyword => {
                    // Highlight keywords (case insensitive)
                    const regex = new RegExp('\\\\b' + keyword + '\\\\b', 'gi');
                    text = text.replace(regex, match => `<span class="sql-keyword">${match}</span>`);
                });
                
                // Restore cursor position after highlighting
                setTimeout(() => {
                    this.setSelectionRange(cursorPos, cursorPos);
                }, 0);
            });
            
            // SQL toolbar buttons
            const sqlButtons = document.querySelectorAll('.sql-toolbar-btn');
            if (sqlButtons) {
                sqlButtons.forEach(button => {
                    button.addEventListener('click', function() {
                        const sqlCmd = this.dataset.sql;
                        if (sqlCmd) {
                            // Insert the SQL command at current cursor position
                            const cursorPos = sqlEditor.selectionStart;
                            const text = sqlEditor.value;
                            const newText = text.substring(0, cursorPos) + sqlCmd + text.substring(cursorPos);
                            sqlEditor.value = newText;
                            
                            // Set cursor after the inserted command
                            sqlEditor.setSelectionRange(cursorPos + sqlCmd.length, cursorPos + sqlCmd.length);
                            sqlEditor.focus();
                        }
                    });
                });
            }
        }
        
        // Pattern editor - Add filter
        const addFilterBtn = document.getElementById('add-filter-btn');
        const filterContainer = document.getElementById('filter-container');
        const filterTemplate = document.getElementById('filter-template');
        if (addFilterBtn && filterContainer && filterTemplate) {
            addFilterBtn.addEventListener('click', function() {
                const newFilter = filterTemplate.cloneNode(true);
                newFilter.style.display = 'flex';
                newFilter.id = 'filter-' + Date.now();
                filterContainer.appendChild(newFilter);
                
                // Add remove filter button event
                newFilter.querySelector('.remove-filter-btn').addEventListener('click', function() {
                    newFilter.remove();
                });
            });
        }
        
        // Aggregation editor - Add aggregation
        const addAggBtn = document.getElementById('add-aggregation-btn');
        const aggContainer = document.getElementById('aggregation-container');
        const aggTemplate = document.getElementById('aggregation-template');
        if (addAggBtn && aggContainer && aggTemplate) {
            addAggBtn.addEventListener('click', function() {
                const newAgg = aggTemplate.cloneNode(true);
                newAgg.style.display = 'flex';
                newAgg.id = 'agg-' + Date.now();
                aggContainer.appendChild(newAgg);
                
                // Add remove aggregation button event
                newAgg.querySelector('.remove-agg-btn').addEventListener('click', function() {
                    newAgg.remove();
                });
            });
        }
        
        // Toggle column visibility
        const toggleColumnBtns = document.querySelectorAll('.toggle-column-btn');
        if (toggleColumnBtns.length > 0) {
            toggleColumnBtns.forEach(btn => {
                btn.addEventListener('click', function() {
                    const columnIndex = parseInt(this.dataset.column);
                    const table = document.querySelector('.result-table table');
                    if (table) {
                        // Toggle column visibility
                        const cells = table.querySelectorAll(`td:nth-child(${columnIndex + 1}), th:nth-child(${columnIndex + 1})`);
                        const isVisible = !cells[0].classList.contains('d-none');
                        
                        cells.forEach(cell => {
                            if (isVisible) {
                                cell.classList.add('d-none');
                                this.classList.remove('btn-primary');
                                this.classList.add('btn-outline-secondary');
                            } else {
                                cell.classList.remove('d-none');
                                this.classList.remove('btn-outline-secondary');
                                this.classList.add('btn-primary');
                            }
                        });
                    }
                });
            });
        }
        
        // Select all features checkbox
        const selectAllFeatures = document.getElementById('select-all-features');
        if (selectAllFeatures) {
            selectAllFeatures.addEventListener('change', function() {
                const featureCheckboxes = document.querySelectorAll('.feature-checkbox');
                featureCheckboxes.forEach(checkbox => {
                    checkbox.checked = this.checked;
                });
            });
        }
        
        // Copy to clipboard button
        const copyResultBtn = document.getElementById('copy-result-btn');
        if (copyResultBtn) {
            copyResultBtn.addEventListener('click', function() {
                const resultTable = document.querySelector('.result-table table');
                if (resultTable) {
                    // Create a range and select the table
                    const range = document.createRange();
                    range.selectNode(resultTable);
                    window.getSelection().removeAllRanges();
                    window.getSelection().addRange(range);
                    
                    // Copy to clipboard
                    try {
                        document.execCommand('copy');
                        window.getSelection().removeAllRanges();
                        
                        // Show success message
                        const originalText = this.innerHTML;
                        this.innerHTML = '<i class="fas fa-check"></i> Copied!';
                        setTimeout(() => {
                            this.innerHTML = originalText;
                        }, 2000);
                    } catch (err) {
                        console.error('Unable to copy', err);
                    }
                }
            });
        }
        
        // Process and submit pattern filters
        const patternForm = document.getElementById('pattern-form');
        if (patternForm) {
            patternForm.addEventListener('submit', function(e) {
                // Prevent default form submission
                e.preventDefault();
                
                // Build filters JSON
                const filters = [];
                const filterItems = document.querySelectorAll('.filter-item:not(#filter-template)');
                
                filterItems.forEach(item => {
                    const column = item.querySelector('.filter-column').value;
                    const operator = item.querySelector('.filter-operator').value;
                    const value = item.querySelector('.filter-value').value;
                    
                    if (column && operator && value) {
                        filters.push({
                            column: column,
                            operator: operator,
                            value: value
                        });
                    }
                });
                
                // Set the query content field
                const queryContent = document.getElementById('pattern-content');
                queryContent.value = JSON.stringify({
                    filters: filters
                });
                
                // Submit the form
                this.submit();
            });
        }
        
        // Process and submit aggregation settings
        const aggregationForm = document.getElementById('aggregation-form');
        if (aggregationForm) {
            aggregationForm.addEventListener('submit', function(e) {
                // Prevent default form submission
                e.preventDefault();
                
                // Get group by columns
                const groupBySelect = document.getElementById('group-by-select');
                const groupBy = Array.from(groupBySelect.selectedOptions).map(option => option.value);
                
                // Build aggregations
                const aggregations = [];
                const aggItems = document.querySelectorAll('.aggregation-item:not(#aggregation-template)');
                
                aggItems.forEach(item => {
                    const column = item.querySelector('.agg-column').value;
                    const func = item.querySelector('.agg-function').value;
                    
                    if (column && func) {
                        aggregations.push({
                            column: column,
                            function: func
                        });
                    }
                });
                
                // Build having conditions if present
                const having = [];
                const havingColumn = document.getElementById('having-column');
                const havingOperator = document.getElementById('having-operator');
                const havingValue = document.getElementById('having-value');
                
                if (havingColumn && havingOperator && havingValue &&
                    havingColumn.value && havingOperator.value && havingValue.value) {
                    having.push({
                        column: havingColumn.value,
                        operator: havingOperator.value,
                        value: havingValue.value
                    });
                }
                
                // Build sort settings
                let sort_by = {};
                const sortColumn = document.getElementById('sort-column');
                const sortDirection = document.getElementById('sort-direction');
                
                if (sortColumn && sortDirection && sortColumn.value) {
                    sort_by = {
                        column: sortColumn.value,
                        direction: sortDirection.value
                    };
                }
                
                // Get limit if present
                let limit = null;
                const limitInput = document.getElementById('limit-input');
                if (limitInput && limitInput.value) {
                    limit = parseInt(limitInput.value);
                }
                
                // Set the query content field
                const queryContent = document.getElementById('aggregation-content');
                queryContent.value = JSON.stringify({
                    group_by: groupBy,
                    aggregations: aggregations,
                    having: having.length > 0 ? having : undefined,
                    sort_by: Object.keys(sort_by).length > 0 ? sort_by : undefined,
                    limit: limit
                });
                
                // Submit the form
                this.submit();
            });
        }
    });
    
    // Function to download result as CSV
    function downloadResultCSV() {
        const table = document.querySelector('.result-table table');
        if (!table) return;
        
        let csv = [];
        const rows = table.querySelectorAll('tr');
        
        for (let i = 0; i < rows.length; i++) {
            const row = [], cols = rows[i].querySelectorAll('td, th');
            
            for (let j = 0; j < cols.length; j++) {
                // Handle commas and quotes in the data
                let data = cols[j].innerText;
                data = data.replace(/"/g, '""');
                data = `"${data}"`;
                row.push(data);
            }
            
            csv.push(row.join(','));
        }
        
        // Create CSV file and download
        const csvFile = new Blob([csv.join('\\n')], {type: 'text/csv'});
        const downloadLink = document.createElement('a');
        
        downloadLink.download = 'analysis_result_' + new Date().toISOString().slice(0,10) + '.csv';
        downloadLink.href = window.URL.createObjectURL(csvFile);
        downloadLink.style.display = 'none';
        
        document.body.appendChild(downloadLink);
        downloadLink.click();
        document.body.removeChild(downloadLink);
    }
    """
    
    os.makedirs('static/js', exist_ok=True)
    with open('static/js/analysis_module.js', 'w') as f:
        f.write(js)

def generate_templates():
    """Generate basic templates for the analysis module"""
    # Templates will be created as needed in a real application
    # This is a placeholder function
    pass
