locals {
  datasets = {
    bronze    = "bronze"
    metadata  = "metadata"
    reference = "${var.dbt_dataset_prefix}_reference"
    silver    = "${var.dbt_dataset_prefix}_silver"
    gold      = "${var.dbt_dataset_prefix}_gold"
  }

  labels = {
    application = "mlb-pitch-analytics"
    environment = var.environment
    managed_by  = "terraform"
  }
}

resource "google_storage_bucket" "bronze_landing" {
  name                        = var.landing_bucket_name
  project                     = var.project_id
  location                    = var.bigquery_location
  force_destroy               = false
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = local.labels

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age            = 30
      matches_prefix = ["tmp/"]
    }
    action {
      type = "Delete"
    }
  }
}

resource "google_bigquery_dataset" "medallion" {
  for_each = local.datasets

  project                    = var.project_id
  dataset_id                 = each.value
  friendly_name              = "MLB ${title(each.key)} (${var.environment})"
  description                = "Terraform-managed ${each.key} layer for MLB pitch analytics."
  location                   = var.bigquery_location
  delete_contents_on_destroy = false
  labels                     = local.labels

  default_partition_expiration_ms = null
  default_table_expiration_ms     = null
}

resource "google_bigquery_dataset_iam_member" "dbt_editor" {
  for_each = google_bigquery_dataset.medallion

  project    = each.value.project
  dataset_id = each.value.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${var.dbt_service_account}"
}

resource "google_storage_bucket_iam_member" "dbt_landing_access" {
  bucket = google_storage_bucket.bronze_landing.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.dbt_service_account}"
}
