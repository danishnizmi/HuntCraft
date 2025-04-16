import sqlite3
import os
import click
from flask import current_app, g
from flask.cli import with_appcontext

def get_db():
    """Get database connection with row factory."""
    if 'db' not in g:
        g.db = sqlite3.connect(
            current_app.config['DATABASE_PATH'],
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        g.db.row_factory = sqlite3.Row
    
    return g.db

def close_db(e=None):
    """Close database connection."""
    db = g.pop('db', None)
    
    if db is not None:
        db.close()

def init_db():
    """Initialize the database with schema."""
    db = get_db()
    
    # Import all modules that have create_database_schema functions
    from main import MODULES
    import importlib
    
    for module_name, module_path in MODULES.items():
        try:
            module = importlib.import_module(module_path)
            if hasattr(module, 'create_database_schema'):
                module.create_database_schema(db.cursor())
        except ImportError as e:
            print(f"Failed to import module {module_name}: {str(e)}")
            raise
    
    db.commit()

@click.command('init-db')
@with_appcontext
def init_db_command():
    """Initialize the database."""
    init_db()
    print('Initialized the database.')

def init_app(app):
    """Register database functions with the Flask app."""
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    
    # NEW: Always check if database needs initialization
    with app.app_context():
        ensure_db_directory_exists(app)
        
        # Check if database exists and has required tables
        db_path = app.config.get('DATABASE_PATH')
        needs_init = not os.path.exists(db_path)
        
        # If database doesn't exist, initialize it
        if needs_init:
            print("Database does not exist. Creating and initializing...")
            init_db()
        else:
            # Check if required tables exist
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                # Check for detonation_jobs table
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='detonation_jobs'")
                if not cursor.fetchone():
                    print("Required tables missing. Initializing database...")
                    conn.close()
                    init_db()
                else:
                    conn.close()
            except Exception as e:
                print(f"Error checking database tables: {e}")
                # If there's any error checking tables, reinitialize to be safe
                init_db()

def ensure_db_directory_exists(app):
    """Ensure database directory exists."""
    db_path = app.config.get('DATABASE_PATH', '/app/data/malware_platform.db')
    os.makedirs(os.path.dirname(db_path), exist_ok=True)import sqlite3
import os
import click
from flask import current_app, g
from flask.cli import with_appcontext

def get_db():
    """Get database connection with row factory."""
    if 'db' not in g:
        g.db = sqlite3.connect(
            current_app.config['DATABASE_PATH'],
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        g.db.row_factory = sqlite3.Row
    
    return g.db

def close_db(e=None):
    """Close database connection."""
    db = g.pop('db', None)
    
    if db is not None:
        db.close()

def init_db():
    """Initialize the database with schema."""
    db = get_db()
    
    # Import all modules that have create_database_schema functions
    from main import MODULES
    import importlib
    
    for module_name, module_path in MODULES.items():
        try:
            module = importlib.import_module(module_path)
            if hasattr(module, 'create_database_schema'):
                module.create_database_schema(db.cursor())
        except ImportError as e:
            print(f"Failed to import module {module_name}: {str(e)}")
            raise
    
    db.commit()

@click.command('init-db')
@with_appcontext
def init_db_command():
    """Initialize the database."""
    init_db()
    print('Initialized the database.')

def init_app(app):
    """Register database functions with the Flask app."""
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
    
    # NEW: Always check if database needs initialization
    with app.app_context():
        ensure_db_directory_exists(app)
        
        # Check if database exists and has required tables
        db_path = app.config.get('DATABASE_PATH')
        needs_init = not os.path.exists(db_path)
        
        # If database doesn't exist, initialize it
        if needs_init:
            print("Database does not exist. Creating and initializing...")
            init_db()
        else:
            # Check if required tables exist
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                
                # Check for detonation_jobs table
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='detonation_jobs'")
                if not cursor.fetchone():
                    print("Required tables missing. Initializing database...")
                    conn.close()
                    init_db()
                else:
                    conn.close()
            except Exception as e:
                print(f"Error checking database tables: {e}")
                # If there's any error checking tables, reinitialize to be safe
                init_db()

def ensure_db_directory_exists(app):
    """Ensure database directory exists."""
    db_path = app.config.get('DATABASE_PATH', '/app/data/malware_platform.db')
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
