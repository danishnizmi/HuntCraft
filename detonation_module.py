from flask import Blueprint, request, render_template, current_app, jsonify, flash, redirect, url_for
import sqlite3, json, time, logging, uuid, os
from datetime import datetime
from google.cloud import compute_v1, storage, pubsub_v1
from google.cloud.functions_v1 import CloudFunctionsServiceClient
from google.cloud import monitoring_v3

# Blueprint and logging setup
detonation_bp = Blueprint('detonation', __name__, url_prefix='/detonation')
logger = logging.getLogger(__name__)
active_jobs = {}  # Global jobs tracker

def init_app(app):
    """Initialize module with Flask app"""
    app.register_blueprint(detonation_bp)
    with app.app_context():
        # Generate CSS/JS
        os.makedirs('static/css', exist_ok=True)
        os.makedirs('static/js', exist_ok=True)
        os.makedirs('templates', exist_ok=True)
        
        # Ensure detonation_topic exists in Pub/Sub
        ensure_pubsub_topic()

def create_database_schema(cursor):
    """Create database tables"""
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS detonation_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, job_uuid TEXT NOT NULL,
        sample_id INTEGER NOT NULL, vm_type TEXT NOT NULL, vm_name TEXT,
        status TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        started_at TEXT, completed_at TEXT, error_message TEXT,
        results_path TEXT, user_id INTEGER,
        FOREIGN KEY (sample_id) REFERENCES malware_samples(id),
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS detonation_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL,
        result_type TEXT NOT NULL, result_data TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (job_id) REFERENCES detonation_jobs(id)
    )''')

def _db_connection(row_factory=None):
    """Create a database connection with optional row factory"""
    conn = sqlite3.connect(current_app.config['DATABASE_PATH'])
    if row_factory: conn.row_factory = row_factory
    return conn

def ensure_pubsub_topic():
    """Ensure the Pub/Sub topic for detonation notifications exists"""
    try:
        project_id = current_app.config['GCP_PROJECT_ID']
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(project_id, 'detonation-notifications')
        
        try:
            publisher.get_topic(request={"topic": topic_path})
            logger.info("Detonation PubSub topic already exists")
        except Exception:
            publisher.create_topic(request={"name": topic_path})
            logger.info("Created detonation PubSub topic")
            
            # Create subscription for this app
            subscriber = pubsub_v1.SubscriberClient()
            subscription_path = subscriber.subscription_path(project_id, 'detonation-app-sub')
            subscriber.create_subscription(
                request={"name": subscription_path, "topic": topic_path}
            )
    except Exception as e:
        logger.error(f"Error setting up PubSub topic: {e}")

# Routes
@detonation_bp.route('/')
def index():
    """Main page - list all detonation jobs"""
    jobs = get_detonation_jobs()
    return render_template('detonation_index.html', jobs=jobs, active_vm_count=len(active_jobs))

@detonation_bp.route('/create', methods=['GET', 'POST'])
def create():
    """Create a new detonation job"""
    sample_id = request.args.get('sample_id', type=int)
    if not sample_id:
        flash('No malware sample specified', 'error')
        return redirect(url_for('malware.index'))
    
    from malware_module import get_malware_by_id
    sample = get_malware_by_id(sample_id)
    if not sample:
        flash('Malware sample not found', 'error')
        return redirect(url_for('malware.index'))
    
    if request.method == 'POST':
        try:
            vm_type = request.form.get('vm_type', 'windows-10-x64')
            job_id = create_detonation_job(sample_id, vm_type)
            flash('Detonation job created successfully. VM deployment in progress...', 'success')
            return redirect(url_for('detonation.view', job_id=job_id))
        except Exception as e:
            flash(f'Error creating detonation job: {str(e)}', 'error')
            return redirect(url_for('detonation.create', sample_id=sample_id))
    
    return render_template('detonation_create.html', sample=sample)

@detonation_bp.route('/view/<int:job_id>')
def view(job_id):
    """View detonation job and results"""
    job = get_job_by_id(job_id)
    if not job:
        flash('Detonation job not found', 'error')
        return redirect(url_for('detonation.index'))
    
    from malware_module import get_malware_by_id
    sample = get_malware_by_id(job['sample_id'])
    results = get_job_results(job_id) if job['status'] == 'completed' else []
    
    return render_template('detonation_view.html', job=job, sample=sample, results=results)

@detonation_bp.route('/cancel/<int:job_id>', methods=['POST'])
def cancel(job_id):
    """Cancel a running detonation job"""
    job = get_job_by_id(job_id)
    if not job or job['status'] not in ['queued', 'deploying', 'running']:
        flash('Cannot cancel this job', 'error')
        return redirect(url_for('detonation.view', job_id=job_id) if job else url_for('detonation.index'))
    
    try:
        success = cancel_detonation_job(job_id)
        flash('Job cancelled successfully' if success else 'Error cancelling job', 'success' if success else 'error')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    
    return redirect(url_for('detonation.view', job_id=job_id))

@detonation_bp.route('/delete/<int:job_id>', methods=['POST'])
def delete(job_id):
    """Delete a detonation job and its results"""
    success = delete_detonation_job(job_id)
    flash('Job deleted successfully' if success else 'Error deleting job', 'success' if success else 'error')
    return redirect(url_for('detonation.index'))

@detonation_bp.route('/api/status/<int:job_id>')
def api_status(job_id):
    """API endpoint to get job status"""
    job = get_job_by_id(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    
    return jsonify({
        'job_id': job_id,
        'status': job['status'],
        'started_at': job['started_at'],
        'completed_at': job['completed_at'],
        'error_message': job['error_message']
    })

# Core Detonation Logic
def create_detonation_job(sample_id, vm_type):
    """Create a new detonation job and start VM deployment via GCP"""
    # Check if maximum concurrent detonations reached
    max_concurrent = current_app.config['MAX_CONCURRENT_DETONATIONS']
    if len(active_jobs) >= max_concurrent:
        raise ValueError(f"Maximum concurrent detonations ({max_concurrent}) reached")
    
    # Generate job UUID and create database record
    job_uuid = str(uuid.uuid4())
    
    conn = _db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO detonation_jobs (job_uuid, sample_id, vm_type, status, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
            (job_uuid, sample_id, vm_type, 'queued')
        )
        job_id = cursor.lastrowid
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()
    
    # Start the GCP-based detonation process
    from malware_module import get_malware_by_id
    sample = get_malware_by_id(sample_id)
    
    # Track active job
    active_jobs[job_id] = {'job_uuid': job_uuid, 'status': 'queued'}
    
    # Update job to 'deploying' status
    update_job_status(job_id, 'deploying')
    
    # Start VM deployment using instance template
    try:
        deploy_vm_for_detonation(job_id, job_uuid, sample, vm_type)
    except Exception as e:
        update_job_status(job_id, 'failed', error_message=str(e))
        if job_id in active_jobs:
            del active_jobs[job_id]
        raise e
    
    return job_id

def deploy_vm_for_detonation(job_id, job_uuid, sample, vm_type):
    """Deploy a GCP VM for malware detonation using instance templates"""
    project_id = current_app.config['GCP_PROJECT_ID']
    zone = current_app.config['GCP_ZONE']
    
    # Generate VM name
    vm_name = f"detonation-{job_uuid[:8]}"
    
    # Update job with VM name
    conn = _db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE detonation_jobs SET vm_name = ? WHERE id = ?", (vm_name, job_id))
    conn.commit()
    conn.close()
    
    # Get appropriate instance template based on VM type
    instance_templates = {
        'windows-10-x64': f"projects/{project_id}/global/instanceTemplates/detonation-win10-template",
        'windows-7-x64': f"projects/{project_id}/global/instanceTemplates/detonation-win7-template",
        'ubuntu-20-04': f"projects/{project_id}/global/instanceTemplates/detonation-ubuntu-template"
    }
    
    template_url = instance_templates.get(vm_type, instance_templates['windows-10-x64'])
    
    # Create the VM from template
    instance_client = compute_v1.InstancesClient()
    
    # Create instance from template request
    instance_props = {
        "name": vm_name,
        "metadata": {
            "items": [
                {"key": "job-uuid", "value": job_uuid},
                {"key": "sample-sha256", "value": sample['sha256']},
                {"key": "sample-path", "value": sample['storage_path']},
                {"key": "results-bucket", "value": current_app.config['GCP_RESULTS_BUCKET']},
                {"key": "job-id", "value": str(job_id)},
                {"key": "detonation-timeout", "value": str(current_app.config['DETONATION_TIMEOUT_MINUTES'])},
                {"key": "project-id", "value": project_id}
            ]
        },
        "labels": {
            "purpose": "malware-detonation",
            "job-id": str(job_id),
            "vm-type": vm_type.replace('-', '_')
        }
    }
    
    # Create and start the VM
    operation = instance_client.insert_with_template(
        project=project_id,
        zone=zone,
        instance_resource=instance_props,
        source_instance_template=template_url
    )
    
    # Check for immediate errors
    if operation.error:
        error_messages = [error.message for error in operation.error.errors]
        raise Exception(f"VM creation failed: {', '.join(error_messages)}")
    
    # Set up a job to check for completion
    setup_job_monitoring(job_id, vm_name)
    
    # Update job status to running
    update_job_status(job_id, 'running', started_at=str(time.time()))
    logger.info(f"Detonation VM {vm_name} deployed for job {job_id}")

def setup_job_monitoring(job_id, vm_name):
    """Configure monitoring for the detonation job using GCP Cloud Functions and Pub/Sub"""
    project_id = current_app.config['GCP_PROJECT_ID']
    
    # Create a Pub/Sub publisher
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(project_id, 'detonation-notifications')
    
    # Publish a message to set up monitoring
    message_data = json.dumps({
        'action': 'monitor',
        'job_id': job_id,
        'vm_name': vm_name,
        'timestamp': datetime.now().isoformat()
    }).encode('utf-8')
    
    publisher.publish(topic_path, data=message_data)
    logger.info(f"Set up monitoring for job {job_id}")

def update_job_status(job_id, status, started_at=None, completed_at=None, error_message=None):
    """Update the status of a detonation job"""
    conn = _db_connection()
    cursor = conn.cursor()
    
    try:
        # Build the update query dynamically
        update_fields = ["status = ?"]
        update_values = [status]
        
        if started_at is not None:
            update_fields.append("started_at = ?")
            update_values.append(started_at)
        
        if completed_at is not None:
            update_fields.append("completed_at = ?")
            update_values.append(completed_at)
        
        if error_message is not None:
            update_fields.append("error_message = ?")
            update_values.append(error_message)
        
        # Add job_id to update values
        update_values.append(job_id)
        
        # Execute the query
        query = f"UPDATE detonation_jobs SET {', '.join(update_fields)} WHERE id = ?"
        cursor.execute(query, update_values)
        conn.commit()
        
        # Update active jobs tracker
        if job_id in active_jobs:
            active_jobs[job_id]['status'] = status
        
        logger.info(f"Updated job {job_id} status to {status}")
        
        # If job completed or failed, notify via Pub/Sub
        if status in ['completed', 'failed', 'cancelled']:
            notify_job_completed(job_id, status)
            
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating job {job_id} status: {str(e)}")
    finally:
        conn.close()

def notify_job_completed(job_id, status):
    """Notify job completion via Pub/Sub"""
    try:
        project_id = current_app.config['GCP_PROJECT_ID']
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(project_id, 'detonation-notifications')
        
        message_data = json.dumps({
            'action': 'job_update',
            'job_id': job_id,
            'status': status,
            'timestamp': datetime.now().isoformat()
        }).encode('utf-8')
        
        publisher.publish(topic_path, data=message_data)
    except Exception as e:
        logger.error(f"Error publishing completion notification: {e}")

# This function would be registered as a Pub/Sub subscriber to handle job updates
def handle_job_update(message):
    """Process job update notifications from Pub/Sub"""
    try:
        data = json.loads(message.data.decode('utf-8'))
        job_id = data.get('job_id')
        status = data.get('status')
        results_path = data.get('results_path')
        
        # Update job status in the database
        conn = _db_connection()
        cursor = conn.cursor()
        
        update_fields = ["status = ?"]
        update_values = [status]
        
        if status == 'completed':
            update_fields.append("completed_at = ?")
            update_values.append(str(time.time()))
            
            if results_path:
                update_fields.append("results_path = ?")
                update_values.append(results_path)
                
                # Process results
                process_detonation_results(job_id, results_path)
        
        elif status == 'failed':
            update_fields.append("error_message = ?")
            update_values.append(data.get('error_message', 'Unknown error'))
        
        # Add job_id to update values
        update_values.append(job_id)
        
        # Execute the query
        query = f"UPDATE detonation_jobs SET {', '.join(update_fields)} WHERE id = ?"
        cursor.execute(query, update_values)
        conn.commit()
        
        # Remove from active jobs
        if job_id in active_jobs:
            del active_jobs[job_id]
            
    except Exception as e:
        logger.error(f"Error handling job update: {e}")

def process_detonation_results(job_id, results_path):
    """Process and store detonation results"""
    try:
        # Get the results from GCS
        storage_client = storage.Client()
        bucket = storage_client.bucket(current_app.config['GCP_RESULTS_BUCKET'])
        
        # Fetch summary.json from the results
        summary_blob_name = f"jobs/{get_job_uuid(job_id)}/summary.json"
        summary_blob = bucket.blob(summary_blob_name)
        
        if summary_blob.exists():
            summary_data = json.loads(summary_blob.download_as_string())
            
            # Store summary in database
            conn = _db_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                "INSERT INTO detonation_results (job_id, result_type, result_data, created_at) VALUES (?, ?, ?, datetime('now'))",
                (job_id, 'summary', json.dumps(summary_data))
            )
            
            # Store reference to full results
            cursor.execute(
                "INSERT INTO detonation_results (job_id, result_type, result_data, created_at) VALUES (?, ?, ?, datetime('now'))",
                (job_id, 'archive', json.dumps({'path': results_path}))
            )
            
            conn.commit()
            conn.close()
            
            logger.info(f"Processed results for job {job_id}")
    except Exception as e:
        logger.error(f"Error processing results for job {job_id}: {e}")

def cancel_detonation_job(job_id):
    """Cancel a running detonation job"""
    job = get_job_by_id(job_id)
    if not job:
        return False
    
    # Delete VM if it exists
    if job['vm_name']:
        try:
            project_id = current_app.config['GCP_PROJECT_ID']
            zone = current_app.config['GCP_ZONE']
            
            # Create Compute Engine client
            instance_client = compute_v1.InstancesClient()
            
            # Delete the VM
            operation = instance_client.delete(
                project=project_id,
                zone=zone,
                instance=job['vm_name']
            )
            
            # Check for immediate errors
            if operation.error:
                error_messages = [error.message for error in operation.error.errors]
                logger.error(f"Error deleting VM: {', '.join(error_messages)}")
        except Exception as e:
            logger.error(f"Error deleting VM for job {job_id}: {e}")
    
    # Update job status
    update_job_status(job_id, 'cancelled', error_message="Job cancelled by user")
    
    # Remove from active jobs
    if job_id in active_jobs:
        del active_jobs[job_id]
    
    return True

def delete_detonation_job(job_id):
    """Delete a detonation job and its results"""
    job = get_job_by_id(job_id)
    if not job:
        return False
    
    # Cancel the job if it's running
    if job['status'] in ['queued', 'deploying', 'running']:
        cancel_detonation_job(job_id)
    
    # Delete results from GCS
    if job['results_path'] or job['job_uuid']:
        try:
            storage_client = storage.Client()
            bucket = storage_client.bucket(current_app.config['GCP_RESULTS_BUCKET'])
            
            # Delete all blobs with the job prefix
            for blob in bucket.list_blobs(prefix=f"jobs/{job['job_uuid']}/"):
                blob.delete()
                
            logger.info(f"Deleted GCS results for job {job_id}")
        except Exception as e:
            logger.error(f"Error deleting GCS results: {e}")
    
    # Delete from database
    conn = _db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("DELETE FROM detonation_results WHERE job_id = ?", (job_id,))
        cursor.execute("DELETE FROM detonation_jobs WHERE id = ?", (job_id,))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error deleting job from database: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

# Database retrieval operations
def get_detonation_jobs():
    """Get a list of all detonation jobs"""
    conn = _db_connection(sqlite3.Row)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT j.*, s.name as sample_name, s.sha256 as sample_sha256
        FROM detonation_jobs j
        JOIN malware_samples s ON j.sample_id = s.id
        ORDER BY j.created_at DESC
    """)
    jobs = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return jobs

def get_job_by_id(job_id):
    """Get job information by ID"""
    conn = _db_connection(sqlite3.Row)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT j.*, s.name as sample_name, s.sha256 as sample_sha256
        FROM detonation_jobs j
        JOIN malware_samples s ON j.sample_id = s.id
        WHERE j.id = ?
    """, (job_id,))
    job = cursor.fetchone()
    
    conn.close()
    return dict(job) if job else None

def get_job_uuid(job_id):
    """Get the UUID for a job"""
    conn = _db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT job_uuid FROM detonation_jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    
    conn.close()
    return row[0] if row else None

def get_job_results(job_id):
    """Get results for a specific job"""
    conn = _db_connection(sqlite3.Row)
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM detonation_results WHERE job_id = ?", (job_id,))
    results = [dict(row) for row in cursor.fetchall()]
    
    # Parse JSON result data
    for result in results:
        if result['result_data']:
            try:
                result['result_data'] = json.loads(result['result_data'])
            except:
                pass
    
    conn.close()
    return results

def get_jobs_for_sample(sample_id):
    """Get detonation jobs for a specific malware sample"""
    conn = _db_connection(sqlite3.Row)
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM detonation_jobs WHERE sample_id = ? ORDER BY created_at DESC", (sample_id,))
    jobs = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return jobs
