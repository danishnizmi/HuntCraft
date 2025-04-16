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
  type        = string
}

variable "zone" {
  description = "GCP Zone"
  default     = "us-central1-a"
  type        = string
}

# Network resources for VM isolation
resource "google_compute_network" "detonation_network" {
  name                    = "detonation-network"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "detonation_subnet" {
  name          = "detonation-subnet"
  ip_cidr_range = "10.0.0.0/24"
  region        = var.region
  network       = google_compute_network.detonation_network.id
}

# Firewall rule for VM analysis tools
resource "google_compute_firewall" "allow_internal" {
  name    = "allow-internal"
  network = google_compute_network.detonation_network.id
  
  allow {
    protocol = "tcp"
  }
  allow {
    protocol = "udp"
  }
  allow {
    protocol = "icmp"
  }
  
  source_ranges = ["10.0.0.0/24"]
}

# Storage buckets
resource "google_storage_bucket" "malware_samples" {
  name          = "malware-samples-${var.project_id}"
  location      = var.region
  force_destroy = true
  
  uniform_bucket_level_access = true
  
  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type = "Delete"
    }
  }
}

resource "google_storage_bucket" "detonation_results" {
  name          = "detonation-results-${var.project_id}"
  location      = var.region
  force_destroy = true
  
  uniform_bucket_level_access = true
  
  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }
}

# Pub/Sub for notifications
resource "google_pubsub_topic" "detonation_notifications" {
  name = "detonation-notifications"
}

resource "google_pubsub_subscription" "detonation_app_sub" {
  name  = "detonation-app-sub"
  topic = google_pubsub_topic.detonation_notifications.name
  
  ack_deadline_seconds = 60
  
  expiration_policy {
    ttl = "" # Never expire
  }
}

# Service accounts
resource "google_service_account" "malware_platform_sa" {
  account_id   = "malware-platform-sa"
  display_name = "Malware Detonation Platform Service Account"
}

resource "google_service_account" "detonation_vm_sa" {
  account_id   = "detonation-vm"
  display_name = "VM Service Account for Malware Detonation"
}

# IAM bindings
resource "google_project_iam_member" "malware_platform_sa_bindings" {
  for_each = toset([
    "roles/storage.admin",
    "roles/pubsub.editor",
    "roles/compute.admin",
    "roles/secretmanager.secretAccessor"
  ])
  
  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.malware_platform_sa.email}"
}

resource "google_project_iam_member" "detonation_vm_sa_bindings" {
  for_each = toset([
    "roles/storage.objectAdmin",
    "roles/pubsub.publisher"
  ])
  
  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.detonation_vm_sa.email}"
}

# Secret for app key
resource "google_secret_manager_secret" "secret_key" {
  secret_id = "malware-platform-secret-key"
  
  replication {
    automatic = true
  }
}

resource "google_secret_manager_secret_version" "secret_key_version" {
  secret      = google_secret_manager_secret.secret_key.id
  secret_data = random_password.app_secret.result
}

resource "random_password" "app_secret" {
  length  = 32
  special = true
}

# VM instance templates for different OS types
resource "google_compute_instance_template" "windows_10_template" {
  name        = "detonation-win10-template"
  description = "Windows 10 VM template for malware detonation"
  
  machine_type = "e2-medium"
  
  disk {
    source_image = "windows-cloud/windows-10-pro-x64"
    auto_delete  = true
    boot         = true
    disk_type    = "pd-balanced"
    disk_size_gb = 50
  }
  
  network_interface {
    network    = google_compute_network.detonation_network.id
    subnetwork = google_compute_subnetwork.detonation_subnet.id
  }
  
  service_account {
    email  = google_service_account.detonation_vm_sa.email
    scopes = ["cloud-platform"]
  }
  
  metadata = {
    windows-startup-script-ps1 = file("${path.module}/scripts/windows_detonation_setup.ps1")
  }
  
  tags = ["detonation-vm", "windows-10"]
  
  lifecycle {
    create_before_destroy = true
  }
}

resource "google_compute_instance_template" "windows_7_template" {
  name        = "detonation-win7-template"
  description = "Windows 7 VM template for malware detonation"
  
  machine_type = "e2-medium"
  
  disk {
    source_image = "windows-cloud/windows-7-enterprise-x64" # Note: may need custom image
    auto_delete  = true
    boot         = true
    disk_type    = "pd-balanced"
    disk_size_gb = 40
  }
  
  network_interface {
    network    = google_compute_network.detonation_network.id
    subnetwork = google_compute_subnetwork.detonation_subnet.id
  }
  
  service_account {
    email  = google_service_account.detonation_vm_sa.email
    scopes = ["cloud-platform"]
  }
  
  metadata = {
    windows-startup-script-ps1 = file("${path.module}/scripts/windows_detonation_setup.ps1")
  }
  
  tags = ["detonation-vm", "windows-7"]
  
  lifecycle {
    create_before_destroy = true
  }
}

resource "google_compute_instance_template" "ubuntu_template" {
  name        = "detonation-ubuntu-template"
  description = "Ubuntu VM template for malware detonation"
  
  machine_type = "e2-medium"
  
  disk {
    source_image = "ubuntu-os-cloud/ubuntu-2004-lts"
    auto_delete  = true
    boot         = true
    disk_type    = "pd-balanced"
    disk_size_gb = 30
  }
  
  network_interface {
    network    = google_compute_network.detonation_network.id
    subnetwork = google_compute_subnetwork.detonation_subnet.id
  }
  
  service_account {
    email  = google_service_account.detonation_vm_sa.email
    scopes = ["cloud-platform"]
  }
  
  metadata = {
    startup-script = file("${path.module}/scripts/linux_detonation_setup.sh")
  }
  
  tags = ["detonation-vm", "ubuntu"]
  
  lifecycle {
    create_before_destroy = true
  }
}

# Cloud Run service
resource "google_cloud_run_service" "malware_platform" {
  name     = "malware-detonation-platform"
  location = var.region
  
  template {
    metadata {
      annotations = {
        "autoscaling.knative.dev/maxScale" = "10"
        "autoscaling.knative.dev/minScale" = "1"
      }
    }
    
    spec {
      service_account_name = google_service_account.malware_platform_sa.email
      
      containers {
        image = "gcr.io/${var.project_id}/malware-detonation-platform:latest"
        
        resources {
          limits = {
            cpu    = "2"
            memory = "2Gi"
          }
        }
        
        env {
          name  = "DEBUG"
          value = "false"
        }
        
        env {
          name  = "GCP_PROJECT_ID"
          value = var.project_id
        }
        
        env {
          name  = "GCP_STORAGE_BUCKET"
          value = google_storage_bucket.malware_samples.name
        }
        
        env {
          name  = "GCP_RESULTS_BUCKET"
          value = google_storage_bucket.detonation_results.name
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
          name  = "VM_NETWORK"
          value = google_compute_network.detonation_network.name
        }
        
        env {
          name  = "VM_SUBNET"
          value = google_compute_subnetwork.detonation_subnet.name
        }
        
        env {
          name  = "SECRET_KEY"
          value_from {
            secret_key_ref {
              name = google_secret_manager_secret.secret_key.secret_id
              key  = "latest"
            }
          }
        }
        
        env {
          name  = "DATABASE_PATH"
          value = "/app/data/malware_platform.db"
        }
        
        env {
          name  = "MAX_UPLOAD_SIZE_MB"
          value = "100"
        }
        
        env {
          name  = "APP_NAME"
          value = "Malware Detonation Platform"
        }
        
        ports {
          container_port = 8080
        }
      }
    }
  }
  
  traffic {
    percent         = 100
    latest_revision = true
  }
  
  depends_on = [
    google_project_iam_member.malware_platform_sa_bindings
  ]
}

# Allow unauthenticated invocations
resource "google_cloud_run_service_iam_member" "public_access" {
  service  = google_cloud_run_service.malware_platform.name
  location = google_cloud_run_service.malware_platform.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Outputs
output "cloud_run_url" {
  value = google_cloud_run_service.malware_platform.status[0].url
}

output "malware_samples_bucket" {
  value = google_storage_bucket.malware_samples.name
}

output "detonation_results_bucket" {
  value = google_storage_bucket.detonation_results.name
}
