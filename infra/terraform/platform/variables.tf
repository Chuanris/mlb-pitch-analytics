variable "project_id" {
  description = "Google Cloud project created or selected during bootstrap."
  type        = string
}

variable "region" {
  description = "Default Google Cloud region."
  type        = string
  default     = "us-west1"
}

variable "bigquery_location" {
  description = "BigQuery dataset location; all datasets must share it."
  type        = string
  default     = "US"
}

variable "landing_bucket_name" {
  description = "Globally unique GCS bucket for immutable Bronze landing files."
  type        = string
}

variable "dbt_dataset_prefix" {
  description = "Base dataset name used by dbt custom schemas."
  type        = string
  default     = "dbt_mlb"

  validation {
    condition     = length(var.dbt_dataset_prefix) <= 1024 && can(regex("^[A-Za-z_][A-Za-z0-9_]*$", var.dbt_dataset_prefix))
    error_message = "dbt_dataset_prefix must be a valid BigQuery dataset identifier."
  }
}

variable "dbt_service_account" {
  description = "Runtime service-account email emitted by the bootstrap module."
  type        = string
}

variable "environment" {
  description = "Short environment label used on cloud resources."
  type        = string
  default     = "dev"
}
