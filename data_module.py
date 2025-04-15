from flask import Blueprint, request, render_template, current_app, jsonify, flash, redirect, url_for
import pandas as pd
import numpy as np
import sqlite3
import os
import json
from werkzeug.utils import secure_filename
from datetime import datetime
import re

# Create blueprint for this module
data_bp = Blueprint('data', __name__, url_prefix='/data')

# Initialize this module
def init_app(app):
    """Initialize the data module with the Flask app"""
    app.register_blueprint(data_bp)
    
    # Add template filters
    @app.template_filter('format_timestamp')
    def format_timestamp(timestamp):
        """Format a timestamp string"""
        try:
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except:
            return timestamp

# Database schema related functions
def create_database_schema(cursor):
    """Create the necessary database tables for the data module"""
    # Create datasets table to track uploaded data
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS datasets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        table_name TEXT NOT NULL,
        source_type TEXT NOT NULL,
        row_count INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Create data_tags table for tagging datasets
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS data_tags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dataset_id INTEGER,
        tag_name TEXT NOT NULL,
        FOREIGN KEY (dataset_id) REFERENCES datasets(id)
    )
    ''')

# Routes definitions
@data_bp.route('/')
def index():
    """Data module main page"""
    datasets = get_datasets()
    return render_template('data_index.html', datasets=datasets)

@data_bp.route('/upload', methods=['GET', 'POST'])
def upload():
    """Upload data file form and handler"""
    if request.method == 'POST':
        # Check if the post request has the file part
        if 'file' not in request.files:
            flash('No file part', 'error')
            return redirect(request.url)
            
        file = request.files['file']
        
        # If user does not select file, browser also
        # submit an empty part without filename
        if file.filename == '':
            flash('No selected file', 'error')
            return redirect(request.url)
            
        if file:
            # Get form data
            name = request.form.get('name', file.filename)
            description = request.form.get('description', '')
            format_type = request.form.get('format_type', 'csv')
            preprocess = 'preprocess' in request.form
            
            try:
                # Process the file
                dataset_id = process_upload(file, name, description, format_type, preprocess)
                flash(f'File uploaded and processed successfully!', 'success')
                return redirect(url_for('data.view', dataset_id=dataset_id))
            except Exception as e:
                flash(f'Error processing file: {str(e)}', 'error')
                return redirect(request.url)
    
    # GET request - show upload form
    return render_template('data_upload.html')

@data_bp.route('/view/<int:dataset_id>')
def view(dataset_id):
    """View a dataset"""
    dataset = get_dataset_by_id(dataset_id)
    if not dataset:
        flash('Dataset not found', 'error')
        return redirect(url_for('data.index'))
        
    # Get schema information
    schema = get_dataset_schema(dataset_id)
    
    # Get a sample of the data (first 100 rows)
    data_sample = load_dataset(dataset_id, limit=100)
    
    # Convert to records for display
    records = data_sample.to_dict('records')
    columns = data_sample.columns.tolist()
    
    return render_template('data_view.html', 
                          dataset=dataset, 
                          schema=schema,
                          columns=columns, 
                          records=records)

@data_bp.route('/delete/<int:dataset_id>', methods=['POST'])
def delete(dataset_id):
    """Delete a dataset"""
    success = delete_dataset(dataset_id)
    if success:
        flash('Dataset deleted successfully', 'success')
    else:
        flash('Error deleting dataset', 'error')
    return redirect(url_for('data.index'))

@data_bp.route('/api/datasets')
def api_datasets():
    """API endpoint to get all datasets"""
    datasets = get_datasets()
    return jsonify(datasets)

@data_bp.route('/api/dataset/<int:dataset_id>')
def api_dataset(dataset_id):
    """API endpoint to get a specific dataset"""
    dataset = get_dataset_by_id(dataset_id)
    if not dataset:
        return jsonify({'error': 'Dataset not found'}), 404
    
    # Get schema information
    schema = get_dataset_schema(dataset_id)
    dataset['schema'] = schema
    
    # Include sample data if requested
    if request.args.get('include_sample') == 'true':
        limit = request.args.get('limit', 100, type=int)
        data_sample = load_dataset(dataset_id, limit=limit)
        dataset['sample'] = data_sample.to_dict('records')
    
    return jsonify(dataset)

# Data processing functions
def process_upload(file, name, description, format_type, preprocess=True):
    """
    Process an uploaded file and store in the database
    
    Args:
        file: The uploaded file object
        name: Name for the dataset
        description: Description of the dataset
        format_type: File format (csv, json, excel)
        preprocess: Whether to preprocess the data
        
    Returns:
        dataset_id: ID of the stored dataset
    """
    # Step 1: Save the file temporarily
    filename = secure_filename(file.filename)
    upload_folder = current_app.config['UPLOAD_FOLDER']
    os.makedirs(upload_folder, exist_ok=True)
    filepath = os.path.join(upload_folder, filename)
    file.save(filepath)
    
    # Step 2: Ingest the data
    try:
        df = ingest_data(filepath, format_type)
        
        # Step 3: Preprocess if requested
        if preprocess:
            df = preprocess_data(df)
        
        # Step 4: Store the data
        table_name = f"dataset_{int(datetime.now().timestamp())}"
        metadata = {
            'name': name,
            'description': description,
            'source_type': format_type,
        }
        
        dataset_id = store_data(df, table_name, metadata)
        
        return dataset_id
    except Exception as e:
        # Clean up the file on error
        if os.path.exists(filepath):
            os.remove(filepath)
        raise e

def ingest_data(source, format_type, **kwargs):
    """
    Ingest data from a source with a specified format.
    
    Args:
        source: The data source (file path, uploaded file object, etc.)
        format_type: The format of the data ('csv', 'json', etc.)
        **kwargs: Additional parameters for specific format types
        
    Returns:
        A pandas DataFrame containing the ingested data
    """
    format_type = format_type.lower()
    
    # Handle different format types
    if format_type == 'csv':
        return _ingest_csv(source, **kwargs)
    elif format_type == 'json':
        return _ingest_json(source, **kwargs)
    elif format_type == 'excel' or format_type == 'xlsx' or format_type == 'xls':
        return _ingest_excel(source, **kwargs)
    else:
        raise ValueError(f"Unsupported format: {format_type}")

def _ingest_csv(source, **kwargs):
    """Helper function to ingest CSV files"""
    try:
        # Set some sensible defaults for CSV reading
        read_kwargs = {
            'delimiter': kwargs.get('delimiter', ','),
            'encoding': kwargs.get('encoding', 'utf-8'),
            'low_memory': kwargs.get('low_memory', False),
            'na_values': kwargs.get('na_values', ['', 'NULL', 'null', 'NaN', 'None']),
            'parse_dates': kwargs.get('parse_dates', True)
        }
        
        # Update with any additional kwargs
        read_kwargs.update({k: v for k, v in kwargs.items() if k not in read_kwargs})
        
        return pd.read_csv(source, **read_kwargs)
    except Exception as e:
        raise ValueError(f"Error ingesting CSV data: {str(e)}")

def _ingest_json(source, **kwargs):
    """Helper function to ingest JSON files"""
    try:
        # Set some sensible defaults for JSON reading
        read_kwargs = {
            'orient': kwargs.get('orient', 'records'),
            'encoding': kwargs.get('encoding', 'utf-8'),
            'convert_dates': kwargs.get('convert_dates', True)
        }
        
        # Update with any additional kwargs
        read_kwargs.update({k: v for k, v in kwargs.items() if k not in read_kwargs})
        
        return pd.read_json(source, **read_kwargs)
    except Exception as e:
        raise ValueError(f"Error ingesting JSON data: {str(e)}")

def _ingest_excel(source, **kwargs):
    """Helper function to ingest Excel files"""
    try:
        # Set some sensible defaults for Excel reading
        read_kwargs = {
            'sheet_name': kwargs.get('sheet_name', 0),
            'na_values': kwargs.get('na_values', ['', 'NULL', 'null', 'NaN', 'None']),
            'convert_float': kwargs.get('convert_float', True)
        }
        
        # Update with any additional kwargs
        read_kwargs.update({k: v for k, v in kwargs.items() if k not in read_kwargs})
        
        return pd.read_excel(source, **read_kwargs)
    except Exception as e:
        raise ValueError(f"Error ingesting Excel data: {str(e)}")

def preprocess_data(data, options=None):
    """
    Preprocess data according to predefined rules or custom options.
    
    Args:
        data: A pandas DataFrame to preprocess
        options: Dict of preprocessing options to apply
            
    Returns:
        A preprocessed pandas DataFrame
    """
    # Make a copy to avoid modifying the original data
    df = data.copy()
    
    # Default options
    default_options = {
        'handle_missing': True,
        'normalize_timestamps': True,
        'normalize_ips': True,
        'normalize_case': True,
        'drop_duplicates': True,
    }
    
    # Use provided options or defaults
    options = options or {}
    for key, value in default_options.items():
        if key not in options:
            options[key] = value
    
    # Apply preprocessing steps based on options
    if options['handle_missing']:
        df = _handle_missing_values(df)
    
    if options['normalize_timestamps']:
        df = _normalize_timestamps(df)
    
    if options['normalize_ips']:
        df = _normalize_ip_addresses(df)
    
    if options['normalize_case']:
        df = _normalize_text_case(df)
    
    if options['drop_duplicates']:
        df = df.drop_duplicates()
    
    # Add a preprocessed timestamp column
    df['_processed_at'] = datetime.now().isoformat()
    
    return df

def _handle_missing_values(df):
    """Helper function to handle missing values"""
    # For numeric columns, fill with median
    numeric_cols = df.select_dtypes(include=[np.number]).columns
    for col in numeric_cols:
        if df[col].isna().any():
            df[col] = df[col].fillna(df[col].median())
    
    # For string/object columns, fill with "unknown"
    categorical_cols = df.select_dtypes(include=['object', 'category']).columns
    for col in categorical_cols:
        if df[col].isna().any():
            # For IP columns, use a special value
            if any(term in col.lower() for term in ['ip', 'addr', 'host']):
                df[col] = df[col].fillna('0.0.0.0')
            else:
                df[col] = df[col].fillna('unknown')
    
    # For datetime columns, forward fill (assume same as previous event)
    datetime_cols = df.select_dtypes(include=['datetime']).columns
    for col in datetime_cols:
        if df[col].isna().any():
            df[col] = df[col].fillna(method='ffill')
    
    return df

def _normalize_timestamps(df):
    """Helper function to normalize timestamp columns"""
    # Identify timestamp columns 
    timestamp_cols = [
        col for col in df.columns 
        if any(term in col.lower() for term in ['time', 'date', 'timestamp', 'created', 'modified'])
    ]
    
    for col in timestamp_cols:
        if df[col].dtype == 'object':  # Only try to convert string columns
            try:
                # Try to convert the column to datetime format
                df[col] = pd.to_datetime(
                    df[col], 
                    errors='coerce',
                    infer_datetime_format=True
                )
            except:
                # If conversion fails, leave the column as is
                pass
    
    return df

def _normalize_ip_addresses(df):
    """Helper function to normalize IP address columns"""
    # Identify IP address columns
    ip_cols = [
        col for col in df.columns 
        if any(term in col.lower() for term in ['ip', 'addr', 'host', 'src_ip', 'dst_ip', 'source', 'destination'])
        and df[col].dtype == 'object'  # Only consider string columns
    ]
    
    for col in ip_cols:
        # Check if column contains IP-like strings
        sample = df[col].dropna().head(100).astype(str)
        ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
        
        # If at least some values match IP pattern, normalize the column
        if any(sample.str.match(ip_pattern)):
            # Replace invalid IPs with null
            df[col] = df[col].apply(
                lambda x: x if isinstance(x, str) and re.match(ip_pattern, x) else None
            )
            
            # Add network information as new columns
            if df[col].notna().any():
                # Extract first octets for subnet analysis
                try:
                    df[f"{col}_first_octet"] = df[col].str.split('.').str[0].astype(float)
                    df[f"{col}_second_octet"] = df[col].str.split('.').str[1].astype(float)
                    
                    # Create a subnet column (first two octets)
                    df[f"{col}_subnet"] = df[col].apply(
                        lambda x: '.'.join(x.split('.')[:2]) + '.0.0' if isinstance(x, str) else None
                    )
                except:
                    # If extraction fails, don't add the columns
                    pass
    
    return df

def _normalize_text_case(df):
    """Helper function to normalize text case"""
    # Identify columns that should be normalized
    case_sensitive_terms = ['path', 'file', 'directory', 'url', 'uri']
    
    text_cols = df.select_dtypes(include=['object']).columns
    for col in text_cols:
        # Skip columns with case-sensitive information
        if any(term in col.lower() for term in case_sensitive_terms):
            continue
            
        # Skip columns that might contain IP addresses or other numeric patterns
        if any(term in col.lower() for term in ['ip', 'addr', 'host']):
            continue
            
        # Normalize case for text columns
        if col in df.columns:  # Check if column still exists
            try:
                df[col] = df[col].str.lower()
            except:
                # If conversion fails, leave the column as is
                pass
    
    return df

# Database operations
def store_data(data, table_name, metadata=None):
    """
    Store the DataFrame in SQLite database
    
    Args:
        data: DataFrame to store
        table_name: Name of the table
        metadata: Dictionary with additional dataset information
        
    Returns:
        dataset_id: ID of the stored dataset
    """
    # Generate table name if not provided
    if not table_name:
        table_name = f"dataset_{int(datetime.now().timestamp())}"
    
    # Clean table name (remove special characters, spaces)
    table_name = re.sub(r'[^\w]', '_', table_name).lower()
    
    # Create a database connection
    conn = sqlite3.connect(current_app.config['DATABASE_PATH'])
    
    try:
        # Store the data
        data.to_sql(table_name, conn, index=False, if_exists='replace')
        
        # Store metadata
        if metadata is None:
            metadata = {}
            
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO datasets (name, description, table_name, source_type, row_count)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                metadata.get('name', table_name),
                metadata.get('description', ''),
                table_name,
                metadata.get('source_type', 'unknown'),
                len(data)
            )
        )
        dataset_id = cursor.lastrowid
        conn.commit()
        
        return dataset_id
        
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_datasets():
    """Get a list of all available datasets"""
    conn = sqlite3.connect(current_app.config['DATABASE_PATH'])
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM datasets ORDER BY created_at DESC")
    datasets = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return datasets

def get_dataset_by_id(dataset_id):
    """Get dataset information by ID"""
    conn = sqlite3.connect(current_app.config['DATABASE_PATH'])
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,))
    dataset = cursor.fetchone()
    
    conn.close()
    return dict(dataset) if dataset else None

def delete_dataset(dataset_id):
    """Delete a dataset and its table"""
    dataset = get_dataset_by_id(dataset_id)
    if not dataset:
        return False
        
    table_name = dataset['table_name']
    
    conn = sqlite3.connect(current_app.config['DATABASE_PATH'])
    cursor = conn.cursor()
    
    try:
        # Delete the table
        cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
        
        # Delete the dataset record
        cursor.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))
        
        # Delete related tags
        cursor.execute("DELETE FROM data_tags WHERE dataset_id = ?", (dataset_id,))
        
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        return False
    finally:
        conn.close()

def get_dataset_schema(dataset_id):
    """Get schema information for a dataset"""
    dataset = get_dataset_by_id(dataset_id)
    if not dataset:
        return None
        
    table_name = dataset['table_name']
    
    conn = sqlite3.connect(current_app.config['DATABASE_PATH'])
    cursor = conn.cursor()
    
    # Get column information
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [
        {
            'name': row[1],
            'type': row[2],
            'nullable': not row[3],
            'primary_key': row[5] == 1
        }
        for row in cursor.fetchall()
    ]
    
    # Get row count
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    row_count = cursor.fetchone()[0]
    
    conn.close()
    
    return {
        'columns': columns,
        'row_count': row_count,
        'table_name': table_name
    }

def load_dataset(dataset_id, limit=None):
    """Load a dataset into a pandas DataFrame"""
    dataset = get_dataset_by_id(dataset_id)
    if not dataset:
        return None
        
    table_name = dataset['table_name']
    
    conn = sqlite3.connect(current_app.config['DATABASE_PATH'])
    
    if limit:
        query = f"SELECT * FROM {table_name} LIMIT {limit}"
    else:
        query = f"SELECT * FROM {table_name}"
        
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    return df

# UI Generation functions
def generate_css():
    """Generate CSS for the data module"""
    css = """
    /* Data Module CSS */
    .data-card {
        border: 1px solid #eaeaea;
        border-radius: 5px;
        padding: 15px;
        margin-bottom: 20px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    
    .data-table {
        width: 100%;
        border-collapse: collapse;
    }
    
    .data-table th,
    .data-table td {
        padding: 8px;
        text-align: left;
        border-bottom: 1px solid #ddd;
    }
    
    .data-table th {
        background-color: #f5f5f5;
    }
    
    .data-upload-form {
        max-width: 600px;
        margin: 0 auto;
    }
    
    .data-upload-form .form-group {
        margin-bottom: 20px;
    }
    
    .data-stats {
        display: flex;
        flex-wrap: wrap;
        gap: 15px;
        margin-bottom: 20px;
    }
    
    .data-stat-card {
        flex: 1;
        min-width: 150px;
        background-color: #f8f9fa;
        padding: 15px;
        border-radius: 5px;
        text-align: center;
    }
    
    .data-stat-card h3 {
        margin-top: 0;
        color: #495057;
    }
    
    .data-stat-card p {
        font-size: 24px;
        font-weight: bold;
        margin: 10px 0 0;
        color: #4a6fa5;
    }
    """
    
    # Write CSS to file
    os.makedirs('static/css', exist_ok=True)
    with open('static/css/data_module.css', 'w') as f:
        f.write(css)

def generate_js():
    """Generate JavaScript for the data module"""
    js = """
    // Data Module JavaScript
    document.addEventListener('DOMContentLoaded', function() {
        // Handle delete dataset confirmation
        const deleteButtons = document.querySelectorAll('.delete-dataset-btn');
        if (deleteButtons) {
            deleteButtons.forEach(button => {
                button.addEventListener('click', function(e) {
                    if (!confirm('Are you sure you want to delete this dataset? This action cannot be undone.')) {
                        e.preventDefault();
                    }
                });
            });
        }
        
        // Handle file upload preview
        const fileInput = document.getElementById('file-upload');
        const fileLabel = document.querySelector('.custom-file-label');
        
        if (fileInput && fileLabel) {
            fileInput.addEventListener('change', function() {
                const fileName = this.files[0] ? this.files[0].name : 'Choose file';
                fileLabel.textContent = fileName;
            });
        }
        
        // Add table search functionality
        const searchInput = document.getElementById('table-search');
        const dataTable = document.getElementById('data-table');
        
        if (searchInput && dataTable) {
            searchInput.addEventListener('keyup', function() {
                const searchTerm = this.value.toLowerCase();
                const rows = dataTable.querySelectorAll('tbody tr');
                
                rows.forEach(row => {
                    const text = row.textContent.toLowerCase();
                    if (text.includes(searchTerm)) {
                        row.style.display = '';
                    } else {
                        row.style.display = 'none';
                    }
                });
            });
        }
    });
    """
    
    # Write JS to file
    os.makedirs('static/js', exist_ok=True)
    with open('static/js/data_module.js', 'w') as f:
        f.write(js)

def generate_templates():
    """Generate HTML templates for the data module"""
    # Make sure the templates directory exists
    os.makedirs('templates', exist_ok=True)
    
    # Data index template
    data_index_html = """
    {% extends 'base.html' %}
    
    {% block title %}Data Management{% endblock %}
    
    {% block content %}
    <div class="container mt-4">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h1>Data Management</h1>
            <a href="{{ url_for('data.upload') }}" class="btn btn-primary">
                <i class="fas fa-upload"></i> Upload New Data
            </a>
        </div>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="alert alert-{{ category }}">{{ message }}</div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        
        <div class="row mb-4">
            <div class="col-md-3">
                <div class="data-stat-card">
                    <h3>Total Datasets</h3>
                    <p>{{ datasets|length }}</p>
                </div>
            </div>
            {% if datasets %}
            <div class="col-md-3">
                <div class="data-stat-card">
                    <h3>Latest Upload</h3>
                    <p>{{ datasets[0].created_at|format_timestamp }}</p>
                </div>
            </div>
            <div class="col-md-3">
                <div class="data-stat-card">
                    <h3>Most Records</h3>
                    <p>{{ datasets|map(attribute='row_count')|max|default(0) }}</p>
                </div>
            </div>
            <div class="col-md-3">
                <div class="data-stat-card">
                    <h3>File Types</h3>
                    <p>{{ datasets|map(attribute='source_type')|unique|list|length }}</p>
                </div>
            </div>
            {% endif %}
        </div>
        
        {% if datasets %}
            <div class="mb-3">
                <input type="text" id="table-search" class="form-control" placeholder="Search datasets...">
            </div>
            
            <div class="table-responsive">
                <table class="table table-striped data-table" id="data-table">
                    <thead>
                        <tr>
                            <th>Name</th>
                            <th>Description</th>
                            <th>Source Type</th>
                            <th>Row Count</th>
                            <th>Created</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for dataset in datasets %}
                        <tr>
                            <td>{{ dataset.name }}</td>
                            <td>{{ dataset.description }}</td>
                            <td>{{ dataset.source_type }}</td>
                            <td>{{ dataset.row_count }}</td>
                            <td>{{ dataset.created_at|format_timestamp }}</td>
                            <td>
                                <a href="{{ url_for('data.view', dataset_id=dataset.id) }}" class="btn btn-sm btn-info">
                                    <i class="fas fa-eye"></i> View
                                </a>
                                <form method="POST" action="{{ url_for('data.delete', dataset_id=dataset.id) }}" class="d-inline">
                                    <button type="submit" class="btn btn-sm btn-danger delete-dataset-btn">
                                        <i class="fas fa-trash"></i> Delete
                                    </button>
                                </form>
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        {% else %}
            <div class="alert alert-info">
                <p>No datasets found. Please upload a new dataset to get started.</p>
                <a href="{{ url_for('data.upload') }}" class="btn btn-primary">
                    <i class="fas fa-upload"></i> Upload Data
                </a>
            </div>
        {% endif %}
    </div>
    {% endblock %}
    
    {% block scripts %}
    <script src="{{ url_for('static', filename='js/data_module.js') }}"></script>
    {% endblock %}
    """
    
    # Data upload template
    data_upload_html = """
    {% extends 'base.html' %}
    
    {% block title %}Upload Data{% endblock %}
    
    {% block content %}
    <div class="container mt-4">
        <h1>Upload Data</h1>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="alert alert-{{ category }}">{{ message }}</div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        
        <div class="card data-card">
            <div class="card-body">
                <form method="POST" enctype="multipart/form-data" class="data-upload-form">
                    <div class="form-group">
                        <label for="name">Dataset Name:</label>
                        <input type="text" class="form-control" id="name" name="name" required>
                    </div>
                    
                    <div class="form-group">
                        <label for="description">Description:</label>
                        <textarea class="form-control" id="description" name="description" rows="3"></textarea>
                    </div>
                    
                    <div class="form-group">
                        <label for="format_type">File Format:</label>
                        <select class="form-control" id="format_type" name="format_type">
                            <option value="csv">CSV</option>
                            <option value="json">JSON</option>
                            <option value="excel">Excel</option>
                        </select>
                    </div>
                    
                    <div class="form-group">
                        <div class="custom-file">
                            <input type="file" class="custom-file-input" id="file-upload" name="file" required>
                            <label class="custom-file-label" for="file-upload">Choose file</label>
                        </div>
                    </div>
                    
                    <div class="form-group form-check">
                        <input type="checkbox" class="form-check-input" id="preprocess" name="preprocess" checked>
                        <label class="form-check-label" for="preprocess">Preprocess data (normalize timestamps, handle missing values, etc.)</label>
                    </div>
                    
                    <div class="form-group">
                        <button type="submit" class="btn btn-primary">Upload</button>
                        <a href="{{ url_for('data.index') }}" class="btn btn-secondary">Cancel</a>
                    </div>
                </form>
            </div>
        </div>
    </div>
    {% endblock %}
    
    {% block scripts %}
    <script src="{{ url_for('static', filename='js/data_module.js') }}"></script>
    {% endblock %}
    """
    
    # Data view template
    data_view_html = """
    {% extends 'base.html' %}
    
    {% block title %}{{ dataset.name }}{% endblock %}
    
    {% block content %}
    <div class="container mt-4">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h1>{{ dataset.name }}</h1>
            <div>
                <a href="{{ url_for('data.index') }}" class="btn btn-secondary">
                    <i class="fas fa-arrow-left"></i> Back to Datasets
                </a>
                <a href="{{ url_for('analysis.create', dataset_id=dataset.id) }}" class="btn btn-primary">
                    <i class="fas fa-search"></i> Analyze Data
                </a>
            </div>
        </div>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="alert alert-{{ category }}">{{ message }}</div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        
        <div class="row mb-4">
            <div class="col-md-6">
                <div class="data-card">
                    <h3>Dataset Information</h3>
                    <dl class="row">
                        <dt class="col-sm-3">Name:</dt>
                        <dd class="col-sm-9">{{ dataset.name }}</dd>
                        
                        <dt class="col-sm-3">Description:</dt>
                        <dd class="col-sm-9">{{ dataset.description or 'No description' }}</dd>
                        
                        <dt class="col-sm-3">Source Type:</dt>
                        <dd class="col-sm-9">{{ dataset.source_type }}</dd>
                        
                        <dt class="col-sm-3">Row Count:</dt>
                        <dd class="col-sm-9">{{ dataset.row_count }}</dd>
                        
                        <dt class="col-sm-3">Created:</dt>
                        <dd class="col-sm-9">{{ dataset.created_at|format_timestamp }}</dd>
                        
                        <dt class="col-sm-3">Table Name:</dt>
                        <dd class="col-sm-9">{{ dataset.table_name }}</dd>
                    </dl>
                </div>
            </div>
            <div class="col-md-6">
                <div class="data-card">
                    <h3>Schema Information</h3>
                    <div class="table-responsive">
                        <table class="table table-sm">
                            <thead>
                                <tr>
                                    <th>Column</th>
                                    <th>Type</th>
                                    <th>Nullable</th>
                                </tr>
                            </thead>
                            <tbody>
                                {% for column in schema.columns %}
                                <tr>
                                    <td>{{ column.name }}</td>
                                    <td>{{ column.type }}</td>
                                    <td>{{ 'Yes' if column.nullable else 'No' }}</td>
                                </tr>
                                {% endfor %}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
        
        <div class="data-card">
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h3>Data Preview</h3>
                <input type="text" id="table-search" class="form-control form-control-sm w-25" placeholder="Search data...">
            </div>
            <div class="table-responsive">
                <table class="table table-sm table-striped data-table" id="data-table">
                    <thead>
                        <tr>
                            {% for column in columns %}
                            <th>{{ column }}</th>
                            {% endfor %}
                        </tr>
                    </thead>
                    <tbody>
                        {% for record in records %}
                        <tr>
                            {% for column in columns %}
                            <td>{{ record[column] }}</td>
                            {% endfor %}
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
            <div class="text-center mt-3">
                <p>Showing {{ records|length }} of {{ dataset.row_count }} records</p>
            </div>
        </div>
    </div>
    {% endblock %}
    
    {% block scripts %}
    <script src="{{ url_for('static', filename='js/data_module.js') }}"></script>
    {% endblock %}
    """
    
    # Write the templates to files
    with open('templates/data_index.html', 'w') as f:
        f.write(data_index_html)
        
    with open('templates/data_upload.html', 'w') as f:
        f.write(data_upload_html)
        
    with open('templates/data_view.html', 'w') as f:
        f.write(data_view_html)
