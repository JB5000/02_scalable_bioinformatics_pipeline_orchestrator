# Monitoring and Observability

## Prometheus Metrics

The API exposes Prometheus metrics at `/metrics`:

```bash
curl http://localhost:8000/metrics
```

Key metrics:
- `jobs_total` - Total number of jobs submitted
- `jobs_completed_total` - Completed jobs
- `jobs_failed_total` - Failed jobs
- `job_duration_seconds` - Job execution duration
- `http_request_duration_seconds` - API response times
- `http_requests_total` - Total HTTP requests

## Alerting

Alerts are defined in `alerts.yml`:

1. **HighJobFailureRate** - When >10% of jobs fail (warning)
2. **DatabaseDown** - PostgreSQL unavailable (critical)
3. **RedisDown** - Redis cache unavailable (critical)
4. **APILatencyHigh** - P95 latency >1s (warning)
5. **QueueBacklog** - >100 jobs queued (warning)

## Dashboards

Grafana can be configured to import the Prometheus data source:

```bash
# Add Prometheus as data source
curl -X POST http://localhost:3000/api/datasources \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Prometheus",
    "type": "prometheus",
    "url": "http://prometheus:9090",
    "access": "proxy"
  }'
```

Recommended dashboard panels:
- Job submission rate (jobs/min)
- Success rate (%)
- P95 API latency
- Queue length
- Database connections
- Redis memory usage

## Logging

Structured JSON logs to stdout:

```json
{
  "timestamp": "2024-01-15T10:30:45.123456",
  "level": "INFO",
  "logger": "orchestration.engine",
  "message": "Job submitted",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "sample_count": 5
}
```

Filter logs by level:
```bash
# Errors only
docker logs -f orchestrator-api | jq 'select(.level=="ERROR")'

# By component
docker logs -f orchestrator-api | jq 'select(.logger|contains("engine"))'
```

## Health Checks

API health endpoint:
```bash
curl http://localhost:8000/health
```

Response:
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:45.123456",
  "database": "connected",
  "redis": "connected"
}
```

## Performance Tuning

### Database Optimization
```bash
# Check slow queries
SELECT * FROM pg_stat_statements
WHERE mean_exec_time > 100
ORDER BY mean_exec_time DESC;
```

### Redis Monitoring
```bash
# Check memory usage
redis-cli INFO memory

# Monitor key operations
redis-cli MONITOR
```

### API Metrics
```bash
# High latency queries
curl http://localhost:8000/metrics | grep http_request_duration_seconds_bucket | grep le=\"1\"
```
