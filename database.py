import sqlite3
import os
import logging
import click
import time
from flask import current_app, g
from flask.cli import with_appcontext
from contextlib import contextmanager

# Set up logger
logger = logging.getLogger(__name__)

def get_db():
    """Get database connection with row factory.
    
    Returns:
        sqlite3.Connection: Database connection with row factory set
    """
    if 'db' not in g:
        try:
            # Connect to the database with retry mechanism
            max_retries = 3
            retry_delay = 1  # seconds
            
            for attempt in range(max_retries):
                try:
                    g.db = sqlite3.connect(
                        current_app.config['DATABASE_PATH'],
                        detect_types=sqlite3.PARSE_DECLTYPES,
                        timeout=30  # Increase timeout for busy database
                    )
                    g.db.row_factory = sqlite3.Row
                    
                    # Set pragmas for better performance and safety
                    g.db.execute('PRAGMA journal_mode=WAL')  # Write-Ahead Logging for better concurrency
                    g.db.execute('PRAGMA synchronous=NORMAL')  # Balance between safety and speed
                    g.db.execute('PRAGMA foreign_keys=ON')  # Enforce foreign key constraints
                    
                    logger.debug("Database connection established")
                    break
                except sqlite3.OperationalError as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"Database connection attempt {attempt+1} failed: {str(e)}. Retrying in {retry_delay}s...")
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                    else:
                        logger.error(f"Failed to connect to database after {max_retries} attempts: {str(e)}")
                        raise
        except Exception as e:
            logger.error(f"Error connecting to database: {str(e)}")
            raise
    
    return g.db

def close_db(e=None):
    """Close database connection if it exists.
    
    Args:
        e: Optional exception that triggered the close
    """
    db = g.pop('db', None)
    
    if db is not None:
        try:
            db.close()
            logger.debug("Database connection closed")
        except Exception as e:
            logger.error(f"Error closing database connection: {str(e)}")

@contextmanager
def get_db_connection(row_factory=sqlite3.Row):
    """Context manager for database connections outside request context.
    
    Args:
        row_factory: Row factory to use for the connection (default: sqlite3.Row)
        
    Yields:
        sqlite3.Connection: Database connection
    """
    conn = None
    try:
        conn = sqlite3.connect(
            current_app.config['DATABASE_PATH'],
            detect_types=sqlite3.PARSE_DECLTYPES,
            timeout=30
        )
        conn.row_factory = row_factory
        
        # Set pragmas for better performance and safety
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.execute('PRAGMA foreign_keys=ON')
        
        yield conn
    except Exception as e:
        logger.error(f"Error with database connection: {str(e)}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()

def execute_query(query, params=(), fetch_one=False, commit=False):
    """Execute a database query and optionally fetch results or commit.
    
    Args:
        query (str): SQL query to execute
        params (tuple): Parameters for the query
        fetch_one (bool): Whether to fetch one result or all results
        commit (bool): Whether to commit after executing the query
        
    Returns:
        The query results, if any
    """
    db = get_db()
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

def init_db():
    """Initialize the database with schema from all modules.
    
    Creates all tables defined in module schema functions.
    """
    db = get_db()
    cursor = db.cursor()
    
    try:
        # Import all modules that have create_database_schema functions
        from main import MODULES
        import importlib
        
        # Track successfully initialized modules
        initialized_modules = []
        
        for module_name, module_path in MODULES.items():
            try:
                module = importlib.import_module(module_path)
                if hasattr(module, 'create_database_schema'):
                    logger.info(f"Initializing database schema for module {module_name}")
                    module.create_database_schema(cursor)
                    initialized_modules.append(module_name)
                else:
                    logger.debug(f"Module {module_name} has no database schema to initialize")
            except ImportError as e:
                logger.error(f"Failed to import module {module_name}: {str(e)}")
            except Exception as e:
                logger.error(f"Error initializing schema for module {module_name}: {str(e)}")
                # Continue with other modules even if one fails
                
        db.commit()
        logger.info(f"Database initialization complete. Initialized modules: {', '.join(initialized_modules)}")
    except Exception as e:
        db.rollback()
        logger.error(f"Database initialization failed: {str(e)}")
        raise

@click.command('init-db')
@with_appcontext
def init_db_command():
    """Initialize the database (CLI command)."""
    click.echo('Initializing the database...')
    init_db()
    click.echo('Database initialization complete.')

@click.command('check-db')
@with_appcontext
def check_db_command():
    """Check database integrity and connection (CLI command)."""
    try:
        db = get_db()
        cursor = db.cursor()
        
        # Run integrity check
        cursor.execute("PRAGMA integrity_check")
        integrity_result = cursor.fetchone()[0]
        
        # Check foreign keys
        cursor.execute("PRAGMA foreign_key_check")
        fk_violations = cursor.fetchall()
        
        # Get database statistics
        cursor.execute("SELECT count(*) FROM sqlite_master WHERE type='table'")
        table_count = cursor.fetchone()[0]
        
        # Output results
        click.echo(f"Database connection: SUCCESS")
        click.echo(f"Integrity check: {integrity_result}")
        click.echo(f"Foreign key violations: {len(fk_violations)}")
        click.echo(f"Number of tables: {table_count}")
        
        # List tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = cursor.fetchall()
        click.echo("Tables in database:")
        for table in tables:
            click.echo(f"  - {table[0]}")
            
    except Exception as e:
        click.echo(f"Database check failed: {str(e)}", err=True)
        raise

def init_app(app):
    """Register database functions with the Flask app.
    
    Args:
        app: Flask application
    """
    # Register teardown handler
    app.teardown_appcontext(close_db)
    
    # Register CLI commands
    app.cli.add_command(init_db_command)
    app.cli.add_command(check_db_command)
    
    # Check database initialization on startup 
    with app.app_context():
        # Check if database directory exists first
        ensure_db_directory_exists(app)
        
        # Check if database exists and has required tables
        db_path = app.config.get('DATABASE_PATH')
        needs_init = not os.path.exists(db_path)
        
        # Skip heavy database initialization if running in a container
        # where initialization should happen during build
        skip_init = app.config.get('SKIP_DB_INIT', False)
        
        if needs_init and not skip_init:
            logger.info("Database does not exist. Creating and initializing...")
            try:
                init_db()
            except Exception as e:
                logger.error(f"Error during database initialization: {str(e)}")
                # Continue startup even if initialization fails, 
                # we'll handle missing tables at runtime
        elif not skip_init:
            # Check if required tables exist
            try:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    
                    # Check for core tables - can be customized for your specific app
                    core_tables = ['users', 'malware_samples', 'detonation_jobs']
                    missing_tables = []
                    
                    for table in core_tables:
                        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
                        if not cursor.fetchone():
                            missing_tables.append(table)
                    
                    if missing_tables:
                        logger.warning(f"Required tables missing: {', '.join(missing_tables)}. Initializing database...")
                        init_db()
                    else:
                        logger.info("Database check successful - required tables exist")
            except Exception as e:
                logger.error(f"Error checking database tables: {str(e)}")
                if not skip_init:
                    # If there's any error checking tables, reinitialize to be safe
                    logger.warning("Reinitializing database due to error during table check")
                    try:
                        init_db()
                    except Exception as init_err:
                        logger.error(f"Error during database reinitialization: {str(init_err)}")

def ensure_db_directory_exists(app):
    """Ensure database directory exists and is writeable.
    
    Args:
        app: Flask application
    """
    db_path = app.config.get('DATABASE_PATH', '/app/data/malware_platform.db')
    db_dir = os.path.dirname(db_path)
    
    try:
        os.makedirs(db_dir, exist_ok=True)
        logger.info(f"Ensured database directory exists: {db_dir}")
        
        # Verify directory is writeable
        test_file = os.path.join(db_dir, '.write_test')
        with open(test_file, 'w') as f:
            f.write('test')
        os.remove(test_file)
    except Exception as e:
        logger.error(f"Error ensuring database directory exists or is writeable: {str(e)}")
        raise

def get_table_count(table_name):
    """Get the count of rows in a table.
    
    Args:
        table_name (str): Name of the table
        
    Returns:
        int: Number of rows in the table
    """
    try:
        return execute_query(f"SELECT COUNT(*) FROM {table_name}", fetch_one=True)[0]
    except Exception as e:
        logger.error(f"Error getting count for table {table_name}: {str(e)}")
        return 0

def check_database_lock():
    """Check if the database is locked.
    
    Returns:
        bool: True if the database is locked, False otherwise
    """
    try:
        with get_db_connection() as conn:
            conn.execute("BEGIN IMMEDIATE").close()
            return False
    except sqlite3.OperationalError as e:
        if "database is locked" in str(e):
            return True
        raise
    except Exception as e:
        logger.error(f"Error checking database lock: {str(e)}")
        raise

def vacuum_database():
    """Vacuum the database to optimize storage and performance."""
    try:
        with get_db_connection() as conn:
            conn.execute("VACUUM")
        logger.info("Database vacuum completed successfully")
        return True
    except Exception as e:
        logger.error(f"Error vacuuming database: {str(e)}")
        return False
