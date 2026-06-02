# Disaster Recovery (DR) Plan

## Overview
This document outlines the disaster recovery strategies and procedures for ShopSage AI. 

**Objective:** Minimize data loss and downtime in the event of a critical system failure.
- **RPO (Recovery Point Objective):** 1 Hour
- **RTO (Recovery Time Objective):** 4 Hours

## Scenarios & Procedures

### 1. Database (RDS PostgreSQL) Failure
**Symptom:** Application returns `503 Service Unavailable` due to DB connection drops.
**Action:**
1. Log into AWS Console -> RDS.
2. Verify if the multi-AZ automated failover is actively running. Wait 5-10 minutes.
3. If complete failure of primary and standby, initiate manual restore from the latest automated snapshot.
4. Update Terraform `variables.tf` or ECS environment variable with the new RDS endpoint.
5. Restart ECS Service to flush connection pools.

### 2. Cache (ElastiCache Redis) Failure
**Symptom:** Degraded performance, massive latency spikes on API responses, health check shows `degraded`.
**Action:**
1. Redis serves as an ephemeral cache and session store. If the node fails, AWS ElastiCache usually spins up a replacement.
2. If the cluster is completely deleted or unresponsive, provision a new cluster using Terraform (`terraform apply`).
3. Note: User sessions/recent contexts might be lost, but persistent profile data is safe in RDS.

### 3. Application / ECS Cluster Failure
**Symptom:** ALB returns `502 Bad Gateway`. Tasks are failing health checks and constantly restarting.
**Action:**
1. Check CloudWatch logs (`/ecs/shopsage-ai-prod`) for the root cause (e.g., OOM, bad deployment).
2. If due to a bad deployment, rollback the ECS service to the previous Task Definition Revision via AWS Console or CLI.
3. If ECS infrastructure is down in the AZ, verify Multi-AZ deployment is active. 

### 4. Region Failure (us-east-1 goes down)
**Action (Active-Passive Strategy):**
1. Run Terraform apply pointing to `us-west-2`.
2. Restore the latest cross-region RDS snapshot.
3. Update Route53 DNS to point to the new ALB in `us-west-2`.
4. Monitor system until stability is restored.
