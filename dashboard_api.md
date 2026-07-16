# Aegis Dashboard API

This document specifies the response format and schemas for the `/dashboard/summary` endpoint, providing real-time statistics for administrative consoles.

## Endpoint Definition

- **Path**: `/dashboard/summary`
- **Method**: `GET`
- **Auth**: Requires `MANAGE_SYSTEM` permission.
- **Content Type**: `application/json`

## Response Schema

Returns a flat JSON object representing system uptime, success rates, latency averages, and sub-systems status:

```json
{
  "pending_requests": 0,
  "completed_today": 5,
  "failed_today": 1,
  "execution_success_rate": 83.33,
  "average_latency": 120.45,
  "authentication_failures": 2,
  "uptime": 3600.0,
  "active_users": 3,
  "system_health": "healthy"
}
```

### JSON Property Index

1. **`pending_requests`**: Integer count of currently active unexpired requests waiting for operator approval.
2. **`completed_today`**: Number of requests successfully executed today (since midnight UTC).
3. **`failed_today`**: Number of executions that failed today.
4. **`execution_success_rate`**: Percent of successful executions relative to total executed requests.
5. **`average_latency`**: Arithmetic mean duration of executions (in milliseconds).
6. **`authentication_failures`**: Count of failed login attempts.
7. **`uptime`**: System uptime (in seconds) since service initialization.
8. **`active_users`**: Total active operators currently configured in the database.
9. **`system_health`**: Service readiness status (`"healthy"` or `"unhealthy"`).
