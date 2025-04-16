import sqlite3
import os
from flask import current_app, g

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

def init_app(app):
    """Register database functions with the Flask app."""
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)

def init_db_command():
    """Initialize the database."""
    init_db()
    print('Initialized the database.')
