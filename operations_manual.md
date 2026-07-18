# Aegis Operations Manual

This guide describes operational maintenance, manual database cleanup triggers, retention rules, and monitoring dashboard management.

## Scheduled Database Cleanup

The database cleanup scheduler runs inside Aegis to prune old, expired, and completed states. It executes:
1. **At Startup**: LIFESPAN hook automatically cleans database entries.
2. **On Interval**: Runs periodically at the configured `interval_seconds` (default: 3600 seconds/1 hour).
3. **Manual Trigger**: Endpoint `POST /approve/cleanup` allows admins to trigger cleanup on demand.

### Retention Configuration
The retention window is defined in `app/config.py`:
- `AUDIT_RETENTION_DAYS`: Number of days to preserve audit logs. Defaults to `30`.

## Manual Cleanup Request Example

To manually trigger a cleanup task, make a POST request with an operator possessing `MANAGE_SYSTEM` permission:

```bash
curl -X POST http://localhost:9000/approve/cleanup \
  -H "Authorization: Api-Key your-operator-api-key"
```

**Response Format**:
```json
{
  "status": "success",
  "cleanup_results": {
    "deleted_expired": 2,
    "archived_completed": 5,
    "deleted_audits": 12
  }
}
```

## Logs Inspections

Logs are emitted to stdout in structured JSON format. Useful trace variables to query:
- `correlation_id`: Trace all related requests, database operations, and executions.
- `operator_username`: Identify which user approved or requested the operation.
- `tool_name`: Track which MCP tool was executed.
