output "state_bucket_name" {
  description = "GCS bucket for the platform Terraform backend."
  value       = google_storage_bucket.terraform_state.name
}

output "workload_identity_provider" {
  description = "Full Workload Identity Provider resource name for GitHub Actions."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "terraform_service_account" {
  description = "Service account used only for Terraform plan/apply."
  value       = google_service_account.terraform_deployer.email
}

output "dbt_service_account" {
  description = "Least-privilege service account used by dbt and load jobs."
  value       = google_service_account.dbt_runtime.email
}
