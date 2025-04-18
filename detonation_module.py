from flask import Blueprint, request, render_template, current_app, jsonify, flash, redirect, url_for
import sqlite3, json, time, logging, uuid, os, threading
from datetime import datetime

# Set up logger first to capture import errors
logger = logging.getLogger(__name__)

# Create blueprint immediately
detonation_bp = Blueprint('detonation', __name__, url_prefix='/detonation')

# Try to import Google Cloud dependencies with better error handling
GCP_ENABLED = True
try:
    from google.cloud import compute_v1, storage, pubsub_v1
except ImportError:
    GCP_ENABLED = False
    logger.warning("Google Cloud dependencies not available. Some detonation features will be limited.")

# Global jobs tracker
active_jobs = {}

def init_app(app):
    """Initialize module with Flask app"""
    # Register blueprint first to avoid initialization issues
    try:
        app.register_blueprint(detonation_bp)
        logger.info("Detonation blueprint registered successfully")
    except Exception as e:
        logger.error(f"Failed to register detonation blueprint: {e}")
        raise
    
    # Continue with other initialization in a safer way
    try:
        with app.app_context():
            # Create directories
            os.makedirs('static/css', exist_ok=True)
            os.makedirs('static/js', exist_ok=True)
            os.makedirs('templates', exist_ok=True)
            
            # Generate templates
            generate_templates()
            
            # Set up Pub/Sub if running in production and GCP is available
            if app.config.get('ON_CLOUD_RUN', False) and GCP_ENABLED:
                ensure_pubsub_topic()
                setup_pubsub_subscription()
            
        logger.info("Detonation module initialized successfully")
    except Exception as e:
        logger.error(f"Error in detonation module initialization: {e}")
        # Don't re-raise to allow app to start with limited functionality

def create_database_schema(cursor):
    """Create database tables"""
    try:
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
        
        logger.info("Detonation database schema created successfully")
    except Exception as e:
        logger.error(f"Error creating detonation database schema: {e}")
        raise

def _db_connection(row_factory=None):
    """Create a database connection with optional row factory"""
    try:
        conn = sqlite3.connect(current_app.config['DATABASE_PATH'])
        if row_factory: 
            conn.row_factory = row_factory
        return conn
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        raise

def ensure_pubsub_topic():
    """Ensure the Pub/Sub topic for detonation notifications exists"""
    if not GCP_ENABLED:
        logger.warning("GCP dependencies not available. Pub/Sub features disabled.")
        return
        
    try:
        project_id = current_app.config['GCP_PROJECT_ID']
        if not project_id:
            logger.warning("Cannot set up Pub/Sub: No project ID configured")
            return
            
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(project_id, 'detonation-notifications')
        
        try:
            publisher.get_topic(request={"topic": topic_path})
            logger.info("Detonation PubSub topic already exists")
        except Exception:
            publisher.create_topic(request={"name": topic_path})
            logger.info("Created detonation PubSub topic")
    except Exception as e:
        logger.error(f"Error setting up PubSub topic: {e}")

def setup_pubsub_subscription():
    """Set up Pub/Sub subscription for job updates"""
    if not GCP_ENABLED:
        logger.warning("GCP dependencies not available. Pub/Sub features disabled.")
        return
        
    try:
        project_id = current_app.config['GCP_PROJECT_ID']
        if not project_id:
            logger.warning("Cannot set up Pub/Sub: No project ID configured")
            return
            
        # Create subscriber client
        subscriber = pubsub_v1.SubscriberClient()
        subscription_path = subscriber.subscription_path(project_id, 'detonation-app-sub')
        
        try:
            # Check if subscription exists
            subscriber.get_subscription(request={"subscription": subscription_path})
            logger.info(f"Pub/Sub subscription already exists: {subscription_path}")
        except Exception:
            # Create subscription if it doesn't exist
            logger.info(f"Creating new Pub/Sub subscription: {subscription_path}")
            topic_path = f"projects/{project_id}/topics/detonation-notifications"
            subscriber.create_subscription(
                request={"name": subscription_path, "topic": topic_path}
            )
        
        # Start subscriber in a separate thread
        def callback(message):
            try:
                data = json.loads(message.data.decode('utf-8'))
                logger.info(f"Received Pub/Sub message: {data}")
                
                if data.get('action') == 'job_update':
                    handle_job_update(message)
                message.ack()
            except Exception as e:
                logger.error(f"Error handling Pub/Sub message: {e}")
                message.nack()
        
        threading.Thread(
            target=lambda: subscriber.subscribe(subscription_path, callback).result(),
            daemon=True
        ).start()
        
    except Exception as e:
        logger.error(f"Error setting up Pub/Sub subscription: {e}")

# Routes
@detonation_bp.route('/')
def index():
    """Main page - list all detonation jobs"""
    try:
        jobs = get_detonation_jobs()
        return render_template('detonation_index.html', jobs=jobs, active_vm_count=len(active_jobs))
    except Exception as e:
        logger.error(f"Error in detonation index: {e}")
        flash(f"Error loading detonation jobs: {str(e)}", "error")
        return render_template('detonation_index.html', jobs=[], active_vm_count=0)

@detonation_bp.route('/create', methods=['GET', 'POST'])
def create():
    """Create a new detonation job"""
    sample_id = request.args.get('sample_id', type=int)
    if not sample_id:
        flash('No malware sample specified', 'error')
        return redirect(url_for('malware.index'))
    
    try:
        from main import get_module
        malware_module = get_module('malware')
        if malware_module:
            sample = malware_module.get_malware_by_id(sample_id)
        else:
            flash('Malware module not available', 'error')
            return redirect(url_for('malware.index'))
            
        if not sample:
            flash('Malware sample not found', 'error')
            return redirect(url_for('malware.index'))
    except Exception as e:
        logger.error(f"Error loading malware sample: {e}")
        flash('Error loading malware sample', 'error')
        return redirect(url_for('malware.index'))
    
    if request.method == 'POST':
        try:
            vm_type = request.form.get('vm_type', 'windows-10-x64')
            job_id = create_detonation_job(sample_id, vm_type)
            flash('Detonation job created successfully. VM deployment in progress...', 'success')
            return redirect(url_for('detonation.view', job_id=job_id))
        except Exception as e:
            logger.error(f"Error creating detonation job: {e}")
            flash(f'Error creating detonation job: {str(e)}', 'error')
            return redirect(url_for('detonation.create', sample_id=sample_id))
    
    # GET request - show upload form
    return render_template('detonation_create.html', sample=sample)

@detonation_bp.route('/view/<int:job_id>')
def view(job_id):
    """View detonation job and results"""
    try:
        job = get_job_by_id(job_id)
        if not job:
            flash('Detonation job not found', 'error')
            return redirect(url_for('detonation.index'))
        
        from main import get_module
        malware_module = get_module('malware')
        if malware_module:
            sample = malware_module.get_malware_by_id(job['sample_id'])
        else:
            flash('Malware module not available', 'error')
            return redirect(url_for('detonation.index'))
        
        results = get_job_results(job_id) if job['status'] == 'completed' else []
        
        return render_template('detonation_view.html', 
                              job=job, 
                              sample=sample, 
                              results=results)
    except Exception as e:
        logger.error(f"Error viewing detonation job {job_id}: {e}")
        flash(f'Error viewing detonation job: {str(e)}', 'error')
        return redirect(url_for('detonation.index'))

@detonation_bp.route('/cancel/<int:job_id>', methods=['POST'])
def cancel(job_id):
    """Cancel a running detonation job"""
    try:
        job = get_job_by_id(job_id)
        if not job or job['status'] not in ['queued', 'deploying', 'running']:
            flash('Cannot cancel this job', 'error')
            return redirect(url_for('detonation.view', job_id=job_id) if job else url_for('detonation.index'))
        
        success = cancel_detonation_job(job_id)
        flash('Job cancelled successfully' if success else 'Error cancelling job', 'success' if success else 'error')
    except Exception as e:
        logger.error(f"Error cancelling job {job_id}: {e}")
        flash(f'Error: {str(e)}', 'error')
    
    return redirect(url_for('detonation.view', job_id=job_id))

@detonation_bp.route('/delete/<int:job_id>', methods=['POST'])
def delete(job_id):
    """Delete a detonation job and its results"""
    try:
        success = delete_detonation_job(job_id)
        flash('Job deleted successfully' if success else 'Error deleting job', 'success' if success else 'error')
    except Exception as e:
        logger.error(f"Error deleting job {job_id}: {e}")
        flash(f'Error deleting job: {str(e)}', 'error')
    return redirect(url_for('detonation.index'))

@detonation_bp.route('/api/status/<int:job_id>')
def api_status(job_id):
    """API endpoint to get job status"""
    try:
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
    except Exception as e:
        logger.error(f"Error in API status for job {job_id}: {e}")
        return jsonify({'error': str(e)}), 500

# Core Detonation Logic
def create_detonation_job(sample_id, vm_type):
    """Create a new detonation job and start VM deployment via GCP"""
    if not GCP_ENABLED:
        raise ValueError("GCP functionality is disabled. Cannot create detonation job.")
        
    # Check if maximum concurrent detonations reached
    max_concurrent = current_app.config.get('MAX_CONCURRENT_DETONATIONS', 5)
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
    
    # Track active job and update status
    active_jobs[job_id] = {'job_uuid': job_uuid, 'status': 'queued'}
    update_job_status(job_id, 'deploying')
    
    # Start VM deployment using instance template
    try:
        from main import get_module
        malware_module = get_module('malware')
        if malware_module:
            sample = malware_module.get_malware_by_id(sample_id)
            deploy_vm_for_detonation(job_id, job_uuid, sample, vm_type)
        else:
            raise ValueError("Malware module not available")
    except Exception as e:
        update_job_status(job_id, 'failed', error_message=str(e))
        if job_id in active_jobs:
            del active_jobs[job_id]
        raise e
    
    return job_id

def deploy_vm_for_detonation(job_id, job_uuid, sample, vm_type):
    """Deploy a GCP VM for malware detonation with improved reliability"""
    if not GCP_ENABLED:
        raise ValueError("GCP functionality is disabled. Cannot deploy VM.")
        
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
    
    # Create the VM with improved metadata and reliability
    instance_client = compute_v1.InstancesClient()
    
    # Create instance with enhanced metadata
    instance_props = {
        "name": vm_name,
        "metadata": {
            "items": [
                {"key": "job-uuid", "value": job_uuid},
                {"key": "sample-sha256", "value": sample['sha256']},
                {"key": "sample-path", "value": sample['storage_path']},
                {"key": "results-bucket", "value": current_app.config['GCP_RESULTS_BUCKET']},
                {"key": "job-id", "value": str(job_id)},
                {"key": "detonation-timeout", "value": str(current_app.config.get('DETONATION_TIMEOUT_MINUTES', 30))},
                {"key": "project-id", "value": project_id},
                {"key": "shutdown-script", "value": create_shutdown_script()},
                {"key": "health-check-interval", "value": "60"},  # Check health every 60 seconds
            ]
        },
        "labels": {
            "purpose": "malware-detonation",
            "job-id": str(job_id),
            "vm-type": vm_type.replace('-', '_'),
            "created-by": "huntcraft",
            "auto-delete": "true"
        },
        "scheduling": {
            "automaticRestart": False,  # Don't restart if crashes
            "preemptible": current_app.config.get('USE_PREEMPTIBLE_VMS', False)
        }
    }
    
    # Create and start the VM with retry logic
    retry_attempts = 3
    for attempt in range(retry_attempts):
        try:
            logger.info(f"Deploying VM {vm_name} (attempt {attempt+1}/{retry_attempts})")
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
            
            # Set up job monitoring, update status, and schedule cleanup
            setup_job_monitoring(job_id, vm_name)
            update_job_status(job_id, 'running', started_at=str(time.time()))
            schedule_cleanup(job_id, vm_name, 
                            timeout_minutes=current_app.config.get('DETONATION_TIMEOUT_MINUTES', 60))
            
            logger.info(f"Detonation VM {vm_name} deployed for job {job_id}")
            return
        except Exception as e:
            logger.error(f"VM deployment error (attempt {attempt+1}): {str(e)}")
            if attempt == retry_attempts - 1:
                raise
            time.sleep(5)

def create_shutdown_script():
    """Create a shutdown script for graceful VM termination"""
    return """#!/bin/bash
# Set up logging
exec > >(tee /var/log/detonation_shutdown.log) 2>&1
echo "Running shutdown cleanup at $(date)"

# Get metadata
PROJECT_ID=$(curl -s "http://metadata.google.internal/computeMetadata/v1/project/project-id" -H "Metadata-Flavor: Google")
JOB_UUID=$(curl -s "http://metadata.google.internal/computeMetadata/v1/instance/attributes/job-uuid" -H "Metadata-Flavor: Google")
JOB_ID=$(curl -s "http://metadata.google.internal/computeMetadata/v1/instance/attributes/job-id" -H "Metadata-Flavor: Google")
RESULTS_BUCKET=$(curl -s "http://metadata.google.internal/computeMetadata/v1/instance/attributes/results-bucket" -H "Metadata-Flavor: Google")

# Check if we already uploaded results
if ! gsutil -q stat gs://$RESULTS_BUCKET/jobs/$JOB_UUID/summary.json; then
    echo "No results found, sending failure notification"
    
    # Create minimal summary
    echo "{\\\"status\\\": \\\"failed\\\", \\\"error\\\": \\\"VM shutdown without completing analysis\\\"}" > /tmp/summary.json
    
    # Upload minimal summary
    gsutil cp /tmp/summary.json gs://$RESULTS_BUCKET/jobs/$JOB_UUID/summary.json
    
    # Send failure notification
    gcloud pubsub topics publish detonation-notifications --project=$PROJECT_ID --message="{\\\"action\\\":\\\"job_update\\\",\\\"job_id\\\":$JOB_ID,\\\"status\\\":\\\"failed\\\",\\\"error_message\\\":\\\"VM shutdown without completing analysis\\\",\\\"results_path\\\":\\\"jobs/$JOB_UUID/\\\"}"
fi

echo "Shutdown cleanup complete at $(date)"
"""

def setup_job_monitoring(job_id, vm_name):
    """Configure monitoring for the detonation job using Pub/Sub"""
    if not GCP_ENABLED:
        logger.warning(f"GCP functionality is disabled. Skipping job monitoring setup for job {job_id}.")
        return
        
    project_id = current_app.config['GCP_PROJECT_ID']
    
    # Create a Pub/Sub publisher
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(project_id, 'detonation-notifications')
    
    # Publish a monitoring setup message
    try:
        message_data = json.dumps({
            'action': 'monitor',
            'job_id': job_id,
            'vm_name': vm_name,
            'timestamp': datetime.now().isoformat()
        }).encode('utf-8')
        
        publisher.publish(topic_path, data=message_data)
        logger.info(f"Set up monitoring for job {job_id}")
    except Exception as e:
        logger.error(f"Error setting up job monitoring: {e}")

def schedule_cleanup(job_id, vm_name, timeout_minutes=60):
    """Schedule automatic cleanup of a VM after timeout period"""
    def cleanup_task():
        time.sleep(timeout_minutes * 60)
        
        # Check if job still exists and is running
        job = get_job_by_id(job_id)
        if job and job['status'] == 'running':
            logger.warning(f"Job {job_id} (VM {vm_name}) timed out after {timeout_minutes} minutes")
            
            try:
                # Force VM deletion if GCP is enabled
                if GCP_ENABLED:
                    project_id = current_app.config['GCP_PROJECT_ID']
                    zone = current_app.config['GCP_ZONE']
                    
                    instance_client = compute_v1.InstancesClient()
                    instance_client.delete(
                        project=project_id,
                        zone=zone,
                        instance=vm_name
                    )
                
                # Update job status to timed out
                update_job_status(job_id, 'failed', 
                                 error_message=f"Detonation timed out after {timeout_minutes} minutes",
                                 completed_at=str(time.time()))
                
                logger.info(f"Cleaned up timed out VM {vm_name} for job {job_id}")
            except Exception as e:
                logger.error(f"Error cleaning up timed out VM {vm_name}: {str(e)}")
    
    # Start cleanup task in separate thread
    cleanup_thread = threading.Thread(target=cleanup_task)
    cleanup_thread.daemon = True
    cleanup_thread.start()
    logger.info(f"Scheduled cleanup for job {job_id} (VM {vm_name}) after {timeout_minutes} minutes")

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
        if status in ['completed', 'failed', 'cancelled'] and GCP_ENABLED:
            notify_job_completed(job_id, status)
            
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating job {job_id} status: {str(e)}")
    finally:
        conn.close()

def notify_job_completed(job_id, status):
    """Notify job completion via Pub/Sub"""
    if not GCP_ENABLED:
        logger.warning(f"GCP functionality is disabled. Skipping completion notification for job {job_id}.")
        return
        
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
    """Process and store detonation results with enhanced error handling"""
    if not GCP_ENABLED:
        logger.warning(f"GCP functionality is disabled. Skipping results processing for job {job_id}.")
        return
        
    try:
        # Get the results from GCS
        storage_client = storage.Client()
        bucket = storage_client.bucket(current_app.config['GCP_RESULTS_BUCKET'])
        
        # Fetch summary.json from the results
        summary_blob_name = f"{results_path}summary.json"
        summary_blob = bucket.blob(summary_blob_name)
        
        if summary_blob.exists():
            summary_data = json.loads(summary_blob.download_as_string())
            
            # Enhance summary with additional metadata
            summary_data['processed_at'] = datetime.now().isoformat()
            summary_data['job_id'] = job_id
            
            # Extract key artifacts
            artifacts = extract_artifacts_from_results(bucket, results_path)
            if artifacts:
                summary_data['artifacts'] = artifacts
            
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
            
            # Store specialized result types if available
            for result_type in ['network_activity', 'file_changes', 'registry_changes', 'process_tree']:
                if result_type in summary_data:
                    cursor.execute(
                        "INSERT INTO detonation_results (job_id, result_type, result_data, created_at) VALUES (?, ?, ?, datetime('now'))",
                        (job_id, result_type.split('_')[0], json.dumps(summary_data[result_type]))
                    )
            
            conn.commit()
            conn.close()
            
            logger.info(f"Processed results for job {job_id}")
            
            # Generate visualization data if configured
            if current_app.config.get('ENABLE_VISUALIZATION', True):
                try:
                    from main import get_module
                    viz_module = get_module('viz')
                    if viz_module and hasattr(viz_module, 'create_visualization_from_data'):
                        viz_module.create_visualization_from_data(job_id, summary_data)
                except Exception as viz_error:
                    logger.error(f"Visualization generation error: {viz_error}")
        else:
            logger.error(f"No summary.json found for job {job_id} at {summary_blob_name}")
            # Create a minimal error summary
            record_error_result(job_id, "No summary.json found in results")
    except Exception as e:
        logger.error(f"Error processing results for job {job_id}: {e}")
        record_error_result(job_id, str(e))

def record_error_result(job_id, error_message):
    """Record an error in the results table"""
    try:
        conn = _db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO detonation_results (job_id, result_type, result_data, created_at) VALUES (?, ?, ?, datetime('now'))",
            (job_id, 'error', json.dumps({"error": error_message}))
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error recording result error: {e}")

def extract_artifacts_from_results(bucket, results_path):
    """Extract important artifacts from detonation results"""
    if not GCP_ENABLED:
        return {}
        
    artifacts = {}
    
    # Check for common artifact files
    artifact_files = [
        "screenshot.png", 
        "memory_dump.bin",
        "network_capture.pcap",
        "processes.json",
        "registry_changes.json"
    ]
    
    for file in artifact_files:
        blob = bucket.blob(f"{results_path}{file}")
        if blob.exists():
            artifacts[file] = f"{results_path}{file}"
    
    return artifacts

def cancel_detonation_job(job_id):
    """Cancel a running detonation job"""
    job = get_job_by_id(job_id)
    if not job:
        return False
    
    # Delete VM if it exists and GCP is enabled
    if job['vm_name'] and GCP_ENABLED:
        try:
            project_id = current_app.config['GCP_PROJECT_ID']
            zone = current_app.config['GCP_ZONE']
            
            # Create Compute Engine client
            instance_client = compute_v1.InstancesClient()
            
            # Delete the VM
            instance_client.delete(
                project=project_id,
                zone=zone,
                instance=job['vm_name']
            )
            
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
    
    # Delete results from GCS if GCP is enabled
    if (job['results_path'] or job['job_uuid']) and GCP_ENABLED:
        try:
            storage_client = storage.Client()
            bucket = storage_client.bucket(current_app.config['GCP_RESULTS_BUCKET'])
            
            # Delete all blobs with the job prefix
            blobs = list(bucket.list_blobs(prefix=f"jobs/{job['job_uuid']}/"))
            if blobs:
                bucket.delete_blobs(blobs)
                
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
    try:
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
    except Exception as e:
        logger.error(f"Error getting detonation jobs: {e}")
        return []

def get_job_by_id(job_id):
    """Get job information by ID"""
    try:
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
    except Exception as e:
        logger.error(f"Error getting job by ID: {e}")
        return None

def get_job_uuid(job_id):
    """Get the UUID for a job"""
    try:
        conn = _db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT job_uuid FROM detonation_jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
        
        conn.close()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Error getting job UUID: {e}")
        return None

def get_job_results(job_id):
    """Get results for a specific job"""
    try:
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
    except Exception as e:
        logger.error(f"Error getting job results: {e}")
        return []

def get_jobs_for_sample(sample_id):
    """Get detonation jobs for a specific malware sample"""
    try:
        conn = _db_connection(sqlite3.Row)
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM detonation_jobs WHERE sample_id = ? ORDER BY created_at DESC", (sample_id,))
        jobs = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        return jobs
    except Exception as e:
        logger.error(f"Error getting jobs for sample: {e}")
        return []

# Template generation
def generate_templates():
    """Generate detonation module templates if not present"""
    templates = {
        'detonation_index.html': """{% extends 'base.html' %}
{% block title %}Detonation Jobs{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4">
    <h1>Detonation Jobs</h1>
    <div>
        <a href="{{ url_for('malware.index') }}" class="btn btn-outline-primary">
            <i class="fas fa-plus"></i> New Detonation
        </a>
    </div>
</div>

<div class="card">
    <div class="card-header">
        <div class="d-flex justify-content-between align-items-center">
            <h5 class="mb-0">Active VMs: <span class="badge bg-primary">{{ active_vm_count }}</span></h5>
        </div>
    </div>
    <div class="card-body">
        {% if jobs %}
            <div class="table-responsive">
                <table class="table table-hover">
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Sample</th>
                            <th>VM Type</th>
                            <th>Status</th>
                            <th>Created</th>
                            <th>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for job in jobs %}
                        <tr>
                            <td>{{ job.id }}</td>
                            <td>
                                <a href="{{ url_for('malware.view', sample_id=job.sample_id) }}">
                                    {{ job.sample_name }}
                                </a>
                            </td>
                            <td>{{ job.vm_type }}</td>
                            <td>
                                <span class="badge {% if job.status == 'completed' %}bg-success{% elif job.status == 'failed' %}bg-danger{% elif job.status == 'running' %}bg-primary{% else %}bg-secondary{% endif %}" 
                                      data-job-id="{{ job.id }}">
                                    {{ job.status }}
                                </span>
                            </td>
                            <td>{{ job.created_at }}</td>
                            <td>
                                <a href="{{ url_for('detonation.view', job_id=job.id) }}" 
                                   class="btn btn-sm btn-info">
                                    <i class="fas fa-eye"></i>
                                </a>
                                
                                {% if job.status in ['queued', 'deploying', 'running'] %}
                                <form method="POST" action="{{ url_for('detonation.cancel', job_id=job.id) }}" 
                                      class="d-inline">
                                    <button type="submit" class="btn btn-sm btn-warning" 
                                            data-confirm="Are you sure you want to cancel this job?">
                                        <i class="fas fa-stop"></i>
                                    </button>
                                </form>
                                {% endif %}
                                
                                <form method="POST" action="{{ url_for('detonation.delete', job_id=job.id) }}" 
                                      class="d-inline">
                                    <button type="submit" class="btn btn-sm btn-danger" 
                                            data-confirm="Are you sure you want to delete this job?">
                                        <i class="fas fa-trash"></i>
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
                No detonation jobs found. Start by selecting a malware sample to detonate.
            </div>
        {% endif %}
    </div>
</div>
{% endblock %}""",
        
        'detonation_view.html': """{% extends 'base.html' %}
{% block title %}Detonation Job #{{ job.id }}{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4">
    <h1>Detonation Job #{{ job.id }}</h1>
    <div>
        <a href="{{ url_for('detonation.index') }}" class="btn btn-outline-secondary">
            <i class="fas fa-arrow-left"></i> Back to Jobs
        </a>
    </div>
</div>

<div class="row">
    <div class="col-md-6">
        <div class="card mb-4">
            <div class="card-header">
                <h5 class="card-title mb-0">Job Details</h5>
            </div>
            <div class="card-body">
                <table class="table table-sm">
                    <tr>
                        <th>Status:</th>
                        <td>
                            <span class="badge {% if job.status == 'completed' %}bg-success{% elif job.status == 'failed' %}bg-danger{% elif job.status == 'running' %}bg-primary{% else %}bg-secondary{% endif %}" 
                                  data-job-id="{{ job.id }}" 
                                  data-refresh-on-complete="true">
                                {{ job.status }}
                            </span>
                        </td>
                    </tr>
                    <tr>
                        <th>Sample:</th>
                        <td>
                            <a href="{{ url_for('malware.view', sample_id=job.sample_id) }}">
                                {{ sample.name }}
                            </a>
                        </td>
                    </tr>
                    <tr>
                        <th>VM Type:</th>
                        <td>{{ job.vm_type }}</td>
                    </tr>
                    <tr>
                        <th>VM Name:</th>
                        <td>{{ job.vm_name or 'N/A' }}</td>
                    </tr>
                    <tr>
                        <th>Created:</th>
                        <td>{{ job.created_at }}</td>
                    </tr>
                    <tr>
                        <th>Started:</th>
                        <td>{{ job.started_at or 'N/A' }}</td>
                    </tr>
                    <tr>
                        <th>Completed:</th>
                        <td>{{ job.completed_at or 'N/A' }}</td>
                    </tr>
                    {% if job.error_message %}
                    <tr>
                        <th>Error:</th>
                        <td class="text-danger">{{ job.error_message }}</td>
                    </tr>
                    {% endif %}
                </table>
                
                <div class="mt-3">
                    {% if job.status in ['queued', 'deploying', 'running'] %}
                    <form method="POST" action="{{ url_for('detonation.cancel', job_id=job.id) }}" class="d-inline">
                        <button type="submit" class="btn btn-warning" 
                                data-confirm="Are you sure you want to cancel this job?">
                            <i class="fas fa-stop"></i> Cancel Job
                        </button>
                    </form>
                    {% endif %}
                    
                    <form method="POST" action="{{ url_for('detonation.delete', job_id=job.id) }}" class="d-inline">
                        <button type="submit" class="btn btn-danger" 
                                data-confirm="Are you sure you want to delete this job?">
                            <i class="fas fa-trash"></i> Delete Job
                        </button>
                    </form>
                </div>
            </div>
        </div>
        
        <div class="card">
            <div class="card-header">
                <h5 class="card-title mb-0">Sample Information</h5>
            </div>
            <div class="card-body">
                <p><strong>SHA256:</strong> <span class="hash-value">{{ sample.sha256 }}</span></p>
                <p><strong>Type:</strong> {{ sample.file_type }}</p>
                <p><strong>Size:</strong> {{ sample.file_size }}</p>
            </div>
        </div>
    </div>
    
    <div class="col-md-6">
        {% if job.status == 'completed' and results %}
        <div class="card">
            <div class="card-header">
                <h5 class="card-title mb-0">Detonation Results</h5>
            </div>
            <div class="card-body">
                {% for result in results %}
                    {% if result.result_type == 'summary' %}
                        <h6>Summary</h6>
                        <table class="table table-sm">
                            {% for key, value in result.result_data.items() %}
                                {% if key != 'artifacts' and key != 'file_changes' and key != 'network_activity' and key != 'registry_changes' and key != 'process_tree' %}
                                <tr>
                                    <th>{{ key|title }}</th>
                                    <td>
                                        {% if value is string %}
                                            {{ value }}
                                        {% elif value is mapping %}
                                            <pre>{{ value }}</pre>
                                        {% elif value is iterable and value is not string %}
                                            <ul class="mb-0">
                                                {% for item in value %}
                                                <li>{{ item }}</li>
                                                {% endfor %}
                                            </ul>
                                        {% else %}
                                            {{ value }}
                                        {% endif %}
                                    </td>
                                </tr>
                                {% endif %}
                            {% endfor %}
                        </table>
                    {% endif %}
                    
                    {% if result.result_type == 'network' %}
                        <h6 class="mt-4">Network Activity</h6>
                        <div class="table-responsive">
                            <table class="table table-sm table-striped">
                                <thead>
                                    <tr>
                                        <th>Protocol</th>
                                        <th>Destination</th>
                                        <th>Port</th>
                                        <th>Process</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {% for conn in result.result_data %}
                                    <tr>
                                        <td>{{ conn.protocol }}</td>
                                        <td>{{ conn.destination }}</td>
                                        <td>{{ conn.port }}</td>
                                        <td>{{ conn.process_name }}</td>
                                    </tr>
                                    {% endfor %}
                                </tbody>
                            </table>
                        </div>
                    {% endif %}
                    
                    {% if result.result_type == 'file' %}
                        <h6 class="mt-4">File System Changes</h6>
                        <div class="table-responsive">
                            <table class="table table-sm table-striped">
                                <thead>
                                    <tr>
                                        <th>Path</th>
                                        <th>Action</th>
                                        <th>Process</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {% for file in result.result_data %}
                                    <tr>
                                        <td>{{ file.path }}</td>
                                        <td>{{ file.action }}</td>
                                        <td>{{ file.process_name }}</td>
                                    </tr>
                                    {% endfor %}
                                </tbody>
                            </table>
                        </div>
                    {% endif %}
                {% endfor %}
                
                <div class="text-center mt-3">
                    <a href="#" class="btn btn-primary">
                        <i class="fas fa-download"></i> Download Full Results
                    </a>
                </div>
            </div>
        </div>
        {% elif job.status == 'running' %}
        <div class="card">
            <div class="card-header">
                <h5 class="card-title mb-0">Detonation In Progress</h5>
            </div>
            <div class="card-body text-center">
                <div class="spinner-border text-primary" role="status">
                    <span class="visually-hidden">Loading...</span>
                </div>
                <p class="mt-3">The sample is currently being analyzed in a secure environment. 
                   This page will automatically update when results are available.</p>
            </div>
        </div>
        {% elif job.status == 'failed' %}
        <div class="card">
            <div class="card-header bg-danger text-white">
                <h5 class="card-title mb-0">Detonation Failed</h5>
            </div>
            <div class="card-body">
                <div class="alert alert-danger">
                    <i class="fas fa-exclamation-triangle"></i> 
                    {{ job.error_message or 'An unknown error occurred during the detonation process.' }}
                </div>
                <p>Please try again or use a different VM environment for this sample.</p>
            </div>
        </div>
        {% else %}
        <div class="card">
            <div class="card-header">
                <h5 class="card-title mb-0">Results</h5>
            </div>
            <div class="card-body">
                <p class="text-muted">Results will be available once the detonation process completes.</p>
            </div>
        </div>
        {% endif %}
    </div>
</div>
{% endblock %}

{% block scripts %}
<script>
    // Auto-refresh for running jobs
    {% if job.status in ['queued', 'deploying', 'running'] %}
    setTimeout(function() {
        window.location.reload();
    }, 30000);
    {% endif %}
</script>
{% endblock %}""",
        
        'detonation_create.html': """{% extends 'base.html' %}
{% block title %}Create Detonation Job{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-center mb-4">
    <h1>Create Detonation Job</h1>
    <div>
        <a href="{{ url_for('malware.view', sample_id=sample.id) }}" class="btn btn-outline-secondary">
            <i class="fas fa-arrow-left"></i> Back to Sample
        </a>
    </div>
</div>

<div class="row">
    <div class="col-md-6">
        <div class="card mb-4">
            <div class="card-header">
                <h5 class="card-title mb-0">Sample Information</h5>
            </div>
            <div class="card-body">
                <h5>{{ sample.name }}</h5>
                <p class="text-muted">{{ sample.description }}</p>
                
                <p><strong>SHA256:</strong> <span class="hash-value">{{ sample.sha256 }}</span></p>
                <p><strong>Type:</strong> {{ sample.file_type }}</p>
                <p><strong>Size:</strong> {{ sample.file_size }}</p>
            </div>
        </div>
    </div>
    
    <div class="col-md-6">
        <div class="card">
            <div class="card-header">
                <h5 class="card-title mb-0">Detonation Options</h5>
            </div>
            <div class="card-body">
                <form method="POST">
                    <div class="mb-3">
                        <label for="vm_type" class="form-label">Select VM Environment</label>
                        <select class="form-select" id="vm_type" name="vm_type" required>
                            <option value="windows-10-x64">Windows 10 (x64)</option>
                            <option value="windows-7-x64">Windows 7 (x64)</option>
                            <option value="ubuntu-20-04">Ubuntu 20.04</option>
                        </select>
                        <div class="form-text text-muted">
                            Select the most appropriate environment for this malware sample.
                        </div>
                    </div>
                    
                    <div class="mb-3">
                        <div class="form-check">
                            <input class="form-check-input" type="checkbox" id="confirm" required>
                            <label class="form-check-label" for="confirm">
                                I understand this will execute potentially malicious code in an isolated environment.
                            </label>
                        </div>
                    </div>
                    
                    <div class="d-grid">
                        <button type="submit" class="btn btn-primary">
                            <i class="fas fa-flask"></i> Start Detonation
                        </button>
                    </div>
                </form>
            </div>
        </div>
    </div>
</div>

<div class="card mt-4">
    <div class="card-header">
        <h5 class="card-title mb-0">Detonation Process Information</h5>
    </div>
    <div class="card-body">
        <ol>
            <li>The sample will be uploaded to a secure, isolated virtual machine.</li>
            <li>Monitoring tools will be started to capture system changes, network traffic, and behavior.</li>
            <li>The sample will be executed with appropriate privileges.</li>
            <li>All actions will be logged and analyzed.</li>
            <li>Results will be available once the detonation process completes.</li>
        </ol>
        <div class="alert alert-warning">
            <i class="fas fa-exclamation-triangle"></i> 
            The detonation process may take several minutes to complete. Please be patient.
        </div>
    </div>
</div>
{% endblock %}"""
    }
    
    # Create templates if they don't exist
    try:
        for filename, content in templates.items():
            if not os.path.exists(f'templates/{filename}'):
                with open(f'templates/{filename}', 'w') as f:
                    f.write(content)
                logger.info(f"Created template: {filename}")
    except Exception as e:
        logger.error(f"Error generating templates: {e}")
