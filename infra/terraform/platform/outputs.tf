output "landing_bucket_name" {
  description = "GCS Bronze landing bucket consumed by the load step."
  value       = google_storage_bucket.bronze_landing.name
}

output "dataset_ids" {
  description = "BigQuery datasets provisioned for the medallion pipeline."
  value       = { for key, dataset in google_bigquery_dataset.medallion : key => dataset.dataset_id }
}
