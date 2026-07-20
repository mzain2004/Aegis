# Veto Ops Metrics Reference

Below is a complete index of all Prometheus metrics exposed by the Veto Ops service under the `/metrics` endpoint.

## Metric Catalog

### 1. Proxy Request Metrics

| Metric Name | Type | Labels | Description |
|---|---|---|---|
| `proxy_requests_total` | Counter | `method`, `route` | Total proxy requests received by Veto Ops. |
| `proxy_requests_read` | Counter | None | Total read-only (forward-through) requests. |
| `proxy_requests_mutating` | Counter | None | Total mutating (suspended) requests. |
| `proxy_requests_blocked` | Counter | None | Requests blocked due to policy/security checks. |
| `proxy_requests_forwarded` | Counter | None | Requests forwarded to the upstream server. |

### 2. Approval Metrics

| Metric Name | Type | Labels | Description |
|---|---|---|---|
| `approvals_pending` | Gauge | None | Number of requests currently suspended, awaiting operator approval. |
| `approvals_completed` | Counter | None | Total number of approved requests that successfully completed execution. |
| `approvals_failed` | Counter | None | Total number of approved requests that failed execution. |
| `approvals_expired` | Counter | None | Total number of pending requests that expired prior to operator action. |
| `approvals_replayed` | Counter | None | Total number of blocked duplicate approval attempts (Replay protection). |
| `approvals_rejected` | Counter | None | Total number of rejected or mismatch approvals. |

### 3. Execution Metrics

| Metric Name | Type | Labels | Description |
|---|---|---|---|
| `executions_total` | Counter | None | Total number of container executions initiated. |
| `executions_success` | Counter | None | Total number of successful execution completions. |
| `executions_failure` | Counter | None | Total number of failed execution runs. |
| `executions_timeout` | Counter | None | Executions terminated due to timeout limits. |
| `execution_duration_seconds` | Histogram | None | Bucketed duration of execution runs in seconds. |

### 4. Authentication & Security Metrics

| Metric Name | Type | Labels | Description |
|---|---|---|---|
| `authentication_success` | Counter | `username` | Successful operator login events. |
| `authentication_failure` | Counter | `reason` | Failed login attempts (e.g. invalid key). |
| `permission_denied` | Counter | `username`, `permission` | Total permission denial events (RBAC). |

### 5. Database Connection Pool Metrics

| Metric Name | Type | Labels | Description |
|---|---|---|---|
| `db_queries_total` | Counter | None | Total number of database queries executed. |
| `db_transaction_duration` | Histogram | None | Bucketed transaction durations in seconds. |
| `db_pool_connections` | Gauge | None | Number of active database connections in the SQLAlchemy pool. |

### 6. System Health Metrics

| Metric Name | Type | Labels | Description |
|---|---|---|---|
| `startup_timestamp` | Gauge | None | System startup UNIX timestamp. |
| `uptime_seconds` | Gauge | None | System uptime in seconds. |
| `active_pending_requests` | Gauge | None | Unexpired pending requests currently held in the database. |
