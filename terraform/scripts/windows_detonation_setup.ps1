# Windows Detonation VM Setup Script

# Create log file
Start-Transcript -Path "C:\setup_log.txt"

# Install Chocolatey
Write-Output "Installing Chocolatey..."
Set-ExecutionPolicy Bypass -Scope Process -Force
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://chocolatey.org/install.ps1'))

# Install analysis tools
Write-Output "Installing analysis tools..."
choco install -y procmon sysinternals wireshark python3 7zip hashdeep

# Install Python modules
Write-Output "Installing Python modules..."
pip install google-cloud-storage google-cloud-pubsub requests yara-python

# Create working directories
Write-Output "Creating working directories..."
New-Item -ItemType Directory -Force -Path C:\detonation
New-Item -ItemType Directory -Force -Path C:\detonation\samples
New-Item -ItemType Directory -Force -Path C:\detonation\results

# Download detonation scripts
Write-Output "Downloading detonation scripts..."
$gcsURL = "https://storage.googleapis.com/detonation-scripts/windows_detonation.py"
(New-Object System.Net.WebClient).DownloadFile($gcsURL, "C:\detonation\detonation.py")

# Set up scheduled task to run on startup
Write-Output "Setting up scheduled task for detonation script..."
$action = New-ScheduledTaskAction -Execute "python" -Argument "C:\detonation\detonation.py"
$trigger = New-ScheduledTaskTrigger -AtStartup
Register-ScheduledTask -TaskName "MalwareDetonation" -Action $action -Trigger $trigger -User "SYSTEM" -RunLevel Highest -Force

# Disable Windows Defender (for malware analysis)
Write-Output "Configuring Windows Defender..."
Set-MpPreference -DisableRealtimeMonitoring $true
Set-MpPreference -DisableIOAVProtection $true
Set-MpPreference -DisableBehaviorMonitoring $true

# Disable automatic updates
Write-Output "Disabling Windows Updates..."
Stop-Service -Name wuauserv
Set-Service -Name wuauserv -StartupType Disabled

# Install network capture tools and setup
Write-Output "Setting up network capture..."
New-NetFirewallRule -DisplayName "Allow All Inbound" -Direction Inbound -Action Allow

# Create detonation service
$serviceScript = @"
# Malware Detonation Service
import os
import time
import json
import logging
import sys
import subprocess
import requests
from google.cloud import storage, pubsub_v1

# Set up logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                   filename='C:\\detonation\\detonation_service.log')
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
        subprocess.run(['7z', 'a', f'C:\\detonation\\results_{job_uuid}.zip', 'C:\\detonation\\results\\*'])
        
        # Upload archive
        archive_blob = bucket.blob(f'jobs/{job_uuid}/results.zip')
        archive_blob.upload_from_filename(f'C:\\detonation\\results_{job_uuid}.zip')
        
        # Upload summary
        summary_blob = bucket.blob(f'jobs/{job_uuid}/summary.json')
        summary_data = {
            'timestamp': time.time(),
            'status': 'completed',
            'platform': 'windows',
            'files_created': os.listdir('C:\\detonation\\results\\created_files'),
            'registry_changes': 'See detailed results',
            'network_activity': 'See pcap file',
            'processes': 'See procmon log'
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
        
        sample_path = f"C:\\detonation\\samples\\{sample_sha256}"
        blob.download_to_filename(sample_path)
        logger.info(f"Downloaded sample to {sample_path}")
        
        # Start monitoring tools
        os.makedirs('C:\\detonation\\results\\created_files', exist_ok=True)
        os.makedirs('C:\\detonation\\results\\network', exist_ok=True)
        os.makedirs('C:\\detonation\\results\\process', exist_ok=True)
        
        # Start Process Monitor
        subprocess.Popen(['procmon', '/BackingFile', 'C:\\detonation\\results\\process\\procmon.pml', '/Quiet', '/Minimized'])
        
        # Start network capture
        subprocess.Popen(['C:\\Program Files\\Wireshark\\dumpcap.exe', '-i', '1', '-w', 'C:\\detonation\\results\\network\\capture.pcap'])
        
        # Wait a bit for tools to initialize
        time.sleep(5)
        
        # Execute the sample
        logger.info(f"Executing sample {sample_sha256}")
        try:
            subprocess.run([sample_path], timeout=300)
        except subprocess.TimeoutExpired:
            logger.info("Sample execution timed out (normal for malware)")
        except Exception as e:
            logger.warning(f"Error during sample execution: {e}")
        
        # Stop monitoring tools
        subprocess.run(['taskkill', '/F', '/IM', 'procmon.exe'])
        subprocess.run(['taskkill', '/F', '/IM', 'dumpcap.exe'])
        
        # Allow time for processes to fully terminate
        time.sleep(5)
        
        # Convert procmon log to CSV
        subprocess.run(['procmon', '/OpenLog', 'C:\\detonation\\results\\process\\procmon.pml', 
                       '/SaveAs', 'C:\\detonation\\results\\process\\procmon.csv', '/Quiet'])
        
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
"@

$serviceScript | Out-File -FilePath "C:\detonation\detonation_service.py" -Encoding utf8

# Set up auto-shutdown after detonation
Write-Output "Setting up auto-shutdown..."
$shutdownScript = @"
# Add a delay to ensure results are uploaded
Start-Sleep -Seconds 600
# Shutdown the VM
Stop-Computer -Force
"@

$shutdownScript | Out-File -FilePath "C:\detonation\shutdown.ps1" -Encoding utf8

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-File C:\detonation\shutdown.ps1"
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(30)
Register-ScheduledTask -TaskName "DetonationShutdown" -Action $action -Trigger $trigger -User "SYSTEM" -RunLevel Highest -Force

# Complete setup
Write-Output "Setup completed successfully."
Stop-Transcript
