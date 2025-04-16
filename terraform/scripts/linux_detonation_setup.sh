#!/bin/bash

# Linux Detonation VM Setup Script
set -e

# Log setup progress
exec > >(tee /var/log/detonation_setup.log) 2>&1
echo "Starting detonation environment setup at $(date)"

# Update packages
apt-get update
apt-get upgrade -y

# Install analysis tools
echo "Installing analysis tools..."
apt-get install -y \
  python3-pip \
  python3-dev \
  tcpdump \
  tshark \
  strace \
  ltrace \
  sysstat \
  auditd \
  git \
  build-essential \
  libssl-dev \
  jq \
  unzip \
  curl \
  wget

# Install Python modules
echo "Installing Python packages..."
pip3 install \
  google-cloud-storage \
  google-cloud-pubsub \
  requests \
  yara-python \
  psutil

# Install specialized tools
echo "Installing specialized analysis tools..."

# Install Cuckoo dependencies
apt-get install -y \
  libffi-dev \
  libssl-dev \
  libxml2-dev \
  libxslt1-dev \
  libfuzzy-dev \
  libjpeg-dev \
  zlib1g-dev

# Create working directories
echo "Creating working directories..."
mkdir -p /opt/detonation/samples
mkdir -p /opt/detonation/results
mkdir -p /opt/detonation/tools
mkdir -p /opt/detonation/logs

# Configure tcpdump for non-root usage
setcap cap_net_raw,cap_net_admin=eip /usr/bin/tcpdump

# Create detonation script
cat > /opt/detonation/detonation_service.py << 'EOF'
#!/usr/bin/env python3
# Linux Malware Detonation Service

import os
import time
import json
import logging
import sys
import subprocess
import requests
import shutil
from google.cloud import storage, pubsub_v1

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='/opt/detonation/logs/detonation_service.log'
)
logger = logging.getLogger('detonation_service')

def get_metadata(key):
    """Get metadata from GCP metadata server"""
    url = f'http://metadata.google.internal/computeMetadata/v1/instance/attributes/{key}'
    headers = {'Metadata-Flavor': 'Google'}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.text
    return None

def upload_results(job_uuid, results_bucket):
    """Upload results to GCS bucket"""
    try:
        client = storage.Client()
        bucket = client.bucket(results_bucket)
        
        # Create results archive
        shutil.make_archive(
            f'/opt/detonation/results_{job_uuid}',
            'zip',
            '/opt/detonation/results'
        )
        
        # Upload archive
        archive_blob = bucket.blob(f'jobs/{job_uuid}/results.zip')
        archive_blob.upload_from_filename(f'/opt/detonation/results_{job_uuid}.zip')
        
        # Upload summary
        summary_blob = bucket.blob(f'jobs/{job_uuid}/summary.json')
        summary_data = {
            'timestamp': time.time(),
            'status': 'completed',
            'platform': 'linux',
            'files_created': os.listdir('/opt/detonation/results/files'),
            'network_activity': 'See pcap file',
            'processes': 'See strace log'
        }
        summary_blob.upload_from_string(json.dumps(summary_data))
        
        return f'jobs/{job_uuid}'
    except Exception as e:
        logger.error(f"Error uploading results: {e}")
        return None

def notify_completion(job_id, project_id, status, results_path=None, error_message=None):
    """Notify job completion via Pub/Sub"""
    try:
        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(project_id, 'detonation-notifications')
        
        message_data = {
            'action': 'job_update',
            'job_id': job_id,
            'status': status,
            'timestamp': time.time()
        }
        
        if results_path:
            message_data['results_path'] = results_path
            
        if error_message:
            message_data['error_message'] = error_message
            
        publisher.publish(topic_path, json.dumps(message_data).encode('utf-8'))
        logger.info(f"Published job completion notification for job {job_id}")
    except Exception as e:
        logger.error(f"Error publishing notification: {e}")

def run_detonation():
    """Run the detonation process"""
    try:
        # Get metadata
        job_uuid = get_metadata('job-uuid')
        sample_sha256 = get_metadata('sample-sha256')
        sample_path = get_metadata('sample-path')
        results_bucket = get_metadata('results-bucket')
        job_id = get_metadata('job-id')
        project_id = get_metadata('project-id')
        
        if not all([job_uuid, sample_sha256, sample_path, results_bucket, job_id]):
            logger.error("Missing required metadata")
            return
        
        logger.info(f"Starting detonation for job {job_id}, sample {sample_sha256}")
        
        # Download the sample
        client = storage.Client()
        bucket_name = sample_path.split('/')[0]
        blob_path = '/'.join(sample_path.split('/')[1:])
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        
        sample_path = f"/opt/detonation/samples/{sample_sha256}"
        blob.download_to_filename(sample_path)
        os.chmod(sample_path, 0o755)
        logger.info(f"Downloaded sample to {sample_path}")
        
        # Set up result directories
        os.makedirs('/opt/detonation/results/files', exist_ok=True)
        os.makedirs('/opt/detonation/results/network', exist_ok=True)
        os.makedirs('/opt/detonation/results/process', exist_ok=True)
        
        # Start monitoring tools
        # Network capture
        tcpdump_proc = subprocess.Popen([
            'tcpdump', '-i', 'any', '-w', '/opt/detonation/results/network/capture.pcap'
        ])
        
        # File monitoring with auditd
        subprocess.run([
            'auditctl', '-w', '/opt/detonation/samples', '-p', 'rwxa', '-k', 'malware'
        ])
        
        # Wait a bit for tools to initialize
        time.sleep(5)
        
        # Execute the sample with strace
        logger.info(f"Executing sample {sample_sha256}")
        try:
            strace_output = '/opt/detonation/results/process/strace.log'
            with open(strace_output, 'w') as strace_file:
                subprocess.run([
                    'strace', '-f', '-e', 'trace=all', '-o', strace_output,
                    sample_path
                ], timeout=300)
        except subprocess.TimeoutExpired:
            logger.info("Sample execution timed out (normal for malware)")
        except Exception as e:
            logger.warning(f"Error during sample execution: {e}")
        
        # Stop monitoring tools
        tcpdump_proc.terminate()
        subprocess.run(['auditctl', '-D'])
        
        # Collect audit logs
        subprocess.run([
            'ausearch', '-k', 'malware', '-i', 
            '-o', '/opt/detonation/results/process/audit.log'
        ])
        
        # Allow time for processes to fully terminate
        time.sleep(5)
        
        # Upload results
        logger.info("Uploading results")
        results_path = upload_results(job_uuid, results_bucket)
        
        # Notify completion
        if results_path:
            notify_completion(job_id, project_id, 'completed', results_path=results_path)
            logger.info("Detonation completed successfully")
        else:
            notify_completion(job_id, project_id, 'failed', error_message="Failed to upload results")
            logger.error("Failed to upload results")
    
    except Exception as e:
        logger.error(f"Error in detonation process: {e}")
        notify_completion(job_id, project_id, 'failed', error_message=str(e))

if __name__ == '__main__':
    # Wait a bit for network to be ready
    time.sleep(30)
    run_detonation()
    
    # Schedule shutdown
    subprocess.run(['shutdown', '-h', '+10'])
EOF

# Make the script executable
chmod +x /opt/detonation/detonation_service.py

# Create systemd service
cat > /etc/systemd/system/detonation.service << EOF
[Unit]
Description=Malware Detonation Service
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 /opt/detonation/detonation_service.py
Restart=no
WorkingDirectory=/opt/detonation

[Install]
WantedBy=multi-user.target
EOF

# Enable and start the service
systemctl daemon-reload
systemctl enable detonation.service
systemctl start detonation.service

# Final setup message
echo "Setup completed successfully at $(date)"
