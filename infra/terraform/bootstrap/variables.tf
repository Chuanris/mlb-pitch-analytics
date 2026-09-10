variable "project_id" {
  description = "Existing Google Cloud project ID with billing enabled."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a valid Google Cloud project ID."
  }
}

variable "region" {
  description = "Default Google Cloud region."
  type        = string
  default     = "us-west1"
}

variable "state_bucket_name" {
  description = "Globally unique GCS bucket used only for Terraform state."
  type        = string
}

variable "github_repository" {
  description = "GitHub repository allowed to federate, in owner/repository form."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must use owner/repository format."
  }
}

variable "github_branch" {
  description = "Only this branch may assume the deployment identities."
  type        = string
  default     = "main"
}

variable "environment" {
  description = "Short environment label used on cloud resources."
  type        = string
  default     = "dev"
}
