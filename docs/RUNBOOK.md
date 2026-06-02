# Production Runbook

This guide is intended for on-call engineers managing ShopSage AI in production.

## Monitoring & Alerting
- **Logs:** AWS CloudWatch Logs -> `/ecs/shopsage-ai-prod`
- **Metrics:** Datadog / Prometheus -> Query `http_requests_total` and `http_request_duration_seconds`
- **Errors:** Sentry -> Filter by environment `prod`

## Common Operational Tasks

### How to Scale the Application Up/Down
If CPU/Memory utilization > 80% or if massive traffic is expected:
1. Go to AWS ECS Console.
2. Select the `shopsage-cluster-prod`.
3. Select the `shopsage-service-prod`.
4. Click **Update**.
5. Change the **Desired tasks** count (e.g., from 2 to 10).
6. Click **Update Service**.

### How to Restart the Application (Force Fresh Pull)
If you need to force the application to reboot and pull the latest image layer without changing configuration:
```bash
aws ecs update-service \
    --cluster shopsage-cluster-prod \
    --service shopsage-service-prod \
    --force-new-deployment
```

### How to Mitigate a DDoS Attack
If the Rate Limiting middleware isn't sufficient:
1. Open AWS WAF (Web Application Firewall).
2. Attach the `AWSManagedRulesCommonRuleSet` to the Application Load Balancer.
3. Implement IP blocking at the ALB level via WAF IP Sets.

### How to Debug 5xx Errors
1. Obtain the `X-Request-ID` or `Session-ID` from the user report.
2. Search CloudWatch logs for the ID.
3. If it's a timeout (`504 Gateway Timeout`), check if the third-party scraping API or the LLM provider (OpenAI/Anthropic/Gemini) is experiencing an outage.
4. If it's a `500 Internal Server Error`, check Sentry for the stack trace.
