variable "aws_region" {
  description = "The AWS region to deploy infrastructure to"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "The deployment environment (e.g., prod, staging)"
  type        = string
  default     = "prod"
}

variable "db_username" {
  description = "Username for the RDS PostgreSQL instance"
  type        = string
  default     = "shopsage_admin"
  sensitive   = true
}

variable "db_password" {
  description = "Password for the RDS PostgreSQL instance"
  type        = string
  sensitive   = true
}

variable "container_image_tag" {
  description = "Docker image tag pushed to ECR (e.g. latest, v2.1.0)"
  type        = string
  default     = "latest"
}

variable "google_api_key" {
  description = "Google Gemini API key (stored in Secrets Manager for ECS)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "container_port" {
  description = "The port the container listens on"
  type        = number
  default     = 8000
}
