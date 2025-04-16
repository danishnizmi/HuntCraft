# GCP provider configuration
provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

# Variables
variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region"
  default     = "us-central1"
}

variable "zone" {
  description = "GCP Zone"
  default     = "us-central1-a"
}

variable "app_name" {
  description = "Application name"
  default     = "malware-detonation-platform"
}

variable "detonation_timeout_minutes" {
  description = "Maximum time for detonation jobs in minutes"
  default     = 60
}

variable "enable_windows_detonation" {
  description = "Whether to enable Windows detonation VMs"
  default     = true
}

variable "enable_linux_detonation" {
  description = "Whether to enable Linux detonation VMs"
  default     = true
}

variable "max_concurrent_detonations" {
  description = "Maximum number of concurrent detonation jobs"
  default     = 5
}

variable "use_preemptible_vms" {
  description = "Use preemptible VMs for cost savings"
  default     = false
}

# Storage buckets
resource "google_storage_bucket" "malware_samples" {
  name          = "malware-samples-${var.project_id}"
  location      = var.region
  force_destroy = false
  uniform_bucket_level_access = true
  
  lifecycle_rule {
    condition {
      age = 90  # Auto-delete after 90 days
    }
    action {
      type = "Delete"
    }
  }
}

resource "google_storage_bucket" "detonation_results" {
  name          = "detonation-results-${var.project_id}"
  location      = var.region
  force_destroy = false
  uniform_bucket_level_access = true
  
  lifecycle_rule {
    condition {
      age = 30  # Auto-delete after 30 days
    }
    action {
      type = "Delete"
    }
  }
}

# PubSub for detonation notifications
resource "google_pubsub_topic" "detonation_notifications" {
  name = "detonation-notifications"
}

resource "google_pubsub_subscription" "detonation_app_sub" {
  name  = "detonation-app-sub"
  topic = google_pubsub_topic.detonation_notifications.name
  
  ack_deadline_seconds = 20
  
  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }
  
  # Expire messages that aren't acknowledged after 7 days
  message_retention_duration = "604800s"
}

# Service account for detonation VMs
resource "google_service_account" "detonation_service_account" {
  account_id   = "detonation-service"
  display_name = "Malware Detonation Service Account"
}

# Grant permissions to service account
resource "google_project_iam_member" "compute_admin" {
  project = var.project_id
  role    = "roles/compute.admin"
  member  = "serviceAccount:${google_service_account.detonation_service_account.email}"
}

resource "google_project_iam_member" "storage_admin" {
  project = var.project_id
  role    = "roles/storage.admin"
  member  = "serviceAccount:${google_service_account.detonation_service_account.email}"
}

resource "google_project_iam_member" "pubsub_publisher" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.detonation_service_account.email}"
}

# Firewall rules for detonation VMs
resource "google_compute_firewall" "detonation_internal" {
  name    = "detonation-internal"
  network = "default"
  
  # Only allow internal network traffic
  source_ranges = ["10.0.0.0/8"]
  
  allow {
    protocol = "icmp"
  }
  
  allow {
    protocol = "tcp"
    ports    = ["22", "3389"]  # SSH and RDP
  }
  
  target_tags = ["detonation-vm"]
}

resource "google_compute_firewall" "detonation_egress" {
  name    = "detonation-egress"
  network = "default"
  direction = "EGRESS"
  
  # Allow outbound traffic to Google APIs and Cloud Storage
  allow {
    protocol = "tcp"
    ports    = ["443"]
  }
  
  destination_ranges = ["35.190.247.13/32", "35.191.0.0/16", "130.211.0.0/22"]
  target_tags = ["detonation-vm"]
}

# Windows VM Instance Template
resource "google_compute_instance_template" "detonation_win10_template" {
  count        = var.enable_windows_detonation ? 1 : 0
  name_prefix  = "detonation-win10-"
  machine_type = "n1-standard-2"
  
  disk {
    source_image = "projects/windows-cloud/global/images/family/windows-2019"
    auto_delete  = true
    boot         = true
    disk_size_gb = 50
    disk_type    = "pd-ssd"
  }
  
  network_interface {
    network = "default"
    access_config {} # Ephemeral IP
  }
  
  metadata = {
    enable-guest-attributes = "TRUE"
    windows-startup-script-ps1 = <<-EOT
      # Install analysis tools
      mkdir C:\Tools
      # Download SysInternals
      [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
      Invoke-WebRequest -Uri "https://download.sysinternals.com/files/SysinternalsSuite.zip" -OutFile "C:\Tools\SysinternalsSuite.zip"
      Expand-Archive -Path "C:\Tools\SysinternalsSuite.zip" -DestinationPath "C:\Tools"
      
      # Create detonation directory
      mkdir C:\detonation
      
      # Install Google Cloud SDK
      Invoke-WebRequest -Uri "https://dl.google.com/dl/cloudsdk/channels/rapid/GoogleCloudSDKInstaller.exe" -OutFile "C:\GoogleCloudSDKInstaller.exe"
      Start-Process -FilePath "C:\GoogleCloudSDKInstaller.exe" -ArgumentList "/S /noreporting /nostartmenu /nodesktop" -Wait
      
      # Install Process Monitor
      & "C:\Tools\Procmon.exe" /AcceptEula
      
      # Set up auto-cleanup script
      $cleanupScript = @"
      # Cleanup script
      Remove-Item -Path C:\detonation\* -Recurse -Force
      "@
      
      Set-Content -Path "C:\cleanup.ps1" -Value $cleanupScript
    EOT
  }
  
  scheduling {
    automatic_restart   = false
    on_host_maintenance = var.use_preemptible_vms ? "TERMINATE" : "MIGRATE"
    preemptible         = var.use_preemptible_vms
  }
  
  service_account {
    email  = google_service_account.detonation_service_account.email
    scopes = ["cloud-platform"]
  }
  
  tags = ["detonation-vm", "windows-vm"]
  
  lifecycle {
    create_before_destroy = true
  }
}

# Linux VM Instance Template
resource "google_compute_instance_template" "detonation_ubuntu_template" {
  count        = var.enable_linux_detonation ? 1 : 0
  name_prefix  = "detonation-ubuntu-"
  machine_type = "n1-standard-2"
  
  disk {
    source_image = "projects/ubuntu-os-cloud/global/images/family/ubuntu-2004-lts"
    auto_delete  = true
    boot         = true
    disk_size_gb = 50
    disk_type    = "pd-ssd"
  }
  
  network_interface {
    network = "default"
    access_config {} # Ephemeral IP
  }
  
  metadata = {
    enable-guest-attributes = "TRUE"
    startup-script = <<-EOT
      #!/bin/bash
      # Set up logging
      exec > >(tee /var/log/detonation_startup.log) 2>&1
      echo "Starting detonation environment setup at $(date)"
      
      # Install analysis tools
      apt-get update
      apt-get install -y tcpdump wireshark-common tshark clamav strace ltrace curl

      # Install Google Cloud SDK if not already installed
      if [ ! -d /usr/share/google-cloud-sdk ]; then
        echo "Installing Google Cloud SDK"
        curl https://sdk.cloud.google.com | bash -s -- --disable-prompts
        echo "source /usr/share/google-cloud-sdk/path.bash.inc" >> /etc/profile.d/gcloud.sh
        echo "source /usr/share/google-cloud-sdk/completion.bash.inc" >> /etc/profile.d/gcloud.sh
      fi
      
      # Set up analysis environment
      mkdir -p /opt/detonation
      mkdir -p /opt/detonation/logs
      mkdir -p /opt/detonation/results
      
      # Set up permissions
      chmod 777 /opt/detonation -R
      
      echo "Detonation environment setup completed at $(date)"
    EOT
  }
  
  scheduling {
    automatic_restart   = false
    on_host_maintenance = var.use_preemptible_vms ? "TERMINATE" : "MIGRATE"
    preemptible         = var.use_preemptible_vms
  }
  
  service_account {
    email  = google_service_account.detonation_service_account.email
    scopes = ["cloud-platform"]
  }
  
  tags = ["detonation-vm", "linux-vm"]
  
  lifecycle {
    create_before_destroy = true
  }
}

# Main Cloud Run service
resource "google_cloud_run_service" "malware_detonation_platform" {
  name     = var.app_name
  location = var.region
  
  template {
    spec {
      containers {
        image = "gcr.io/${var.project_id}/${var.app_name}:latest"
        
        env {
          name  = "DEBUG"
          value = "false"
        }
        
        env {
          name  = "DATABASE_PATH"
          value = "/app/data/malware_platform.db"
        }
        
        env {
          name  = "UPLOAD_FOLDER"
          value = "/app/data/uploads"
        }
        
        env {
          name  = "MAX_UPLOAD_SIZE_MB"
          value = "100"
        }
        
        env {
          name  = "GCP_PROJECT_ID"
          value = var.project_id
        }
        
        env {
          name  = "GCP_REGION"
          value = var.region
        }
        
        env {
          name  = "GCP_ZONE"
          value = var.zone
        }
        
        env {
          name  = "ON_CLOUD_RUN"
          value = "true"
        }
        
        env {
          name  = "GCP_RESULTS_BUCKET"
          value = google_storage_bucket.detonation_results.name
        }
        
        env {
          name  = "MAX_CONCURRENT_DETONATIONS"
          value = var.max_concurrent_detonations
        }
        
        env {
          name  = "DETONATION_TIMEOUT_MINUTES"
          value = var.detonation_timeout_minutes
        }
        
        env {
          name  = "USE_PREEMPTIBLE_VMS"
          value = var.use_preemptible_vms ? "true" : "false"
        }
        
        env {
          name  = "GENERATE_TEMPLATES"
          value = "true"
        }
        
        resources {
          limits = {
            cpu    = "1000m"
            memory = "512Mi"
          }
        }
      }
    }
  }
  
  traffic {
    percent         = 100
    latest_revision = true
  }
  
  autogenerate_revision_name = true
}

# IAM policy to make the service public
resource "google_cloud_run_service_iam_member" "public_access" {
  service  = google_cloud_run_service.malware_detonation_platform.name
  location = google_cloud_run_service.malware_detonation_platform.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Outputs
output "malware_samples_bucket" {
  value = google_storage_bucket.malware_samples.name
}

output "detonation_results_bucket" {
  value = google_storage_bucket.detonation_results.name
}

output "pubsub_topic" {
  value = google_pubsub_topic.detonation_notifications.name
}

output "service_url" {
  value = google_cloud_run_service.malware_detonation_platform.status[0].url
}

output "windows_template" {
  value = var.enable_windows_detonation ? google_compute_instance_template.detonation_win10_template[0].self_link : "Windows detonation disabled"
}

output "linux_template" {
  value = var.enable_linux_detonation ? google_compute_instance_template.detonation_ubuntu_template[0].self_link : "Linux detonation disabled"
}
