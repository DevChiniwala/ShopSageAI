# ShopSage AI — Terraform (AWS)

This stack provisions VPC networking, ALB, ECS Fargate, RDS PostgreSQL, ElastiCache Redis, and ECR for ShopSage AI.

## Status

**Production readiness:** The application still uses SQLite-backed stores in many modules. RDS is wired via `DATABASE_URL` on ECS tasks, but full Postgres migration is not complete. Treat this stack as infrastructure scaffolding until Alembic migrations and store backends are aligned.

## Prerequisites

- Terraform >= 1.5
- AWS credentials with permissions for VPC, ECS, RDS, ElastiCache, Secrets Manager
- A Docker image pushed to the ECR repository created by this module

## Required variables

Set in `terraform.tfvars` (do not commit secrets):

| Variable | Description |
|----------|-------------|
| `db_password` | RDS master password |
| `google_api_key` | Gemini API key (stored in Secrets Manager) |

Optional: `container_image_tag` (default `latest`), `environment`, `aws_region`.

## Apply

```bash
cd terraform
terraform init
terraform plan -var="db_password=..." -var="google_api_key=..."
terraform apply
```

## Networking

- Public subnets: ALB and NAT gateway
- Private subnets: ECS tasks, RDS, Redis (outbound via NAT)

## Application configuration

ECS tasks receive:

- `DATABASE_URL` — PostgreSQL (asyncpg driver)
- `REDIS_URL` — ElastiCache Redis
- `GOOGLE_API_KEY` — from Secrets Manager

Ensure the container image and application code use these variables (see `shopsage/config.py`).
