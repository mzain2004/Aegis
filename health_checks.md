# Veto Ops Health Checks

Veto Ops provides structured liveness, readiness, and subsystem check endpoints for integration with Kubernetes, Consul, and other container orchestration platforms.

## Endpoint Index

### 1. Health Probe (`/health`)
- **Method**: `GET`
- **Response Code**: `200 OK` (if database connection is healthy), `500 Internal Server Error` (if down).
- **Format**:
  ```json
  { "status": "healthy" }
  ```

### 2. Live Probe (`/live`)
- **Method**: `GET`
- **Response Code**: `200 OK`
- **Format**:
  ```json
  {
    "status": "alive",
    "timestamp": "2026-07-16T04:12:08.127164+00:00"
  }
  ```

### 3. Ready Probe (`/ready`)
- **Method**: `GET`
- **Response Code**: `200 OK` (if all checks pass), `503 Service Unavailable` (if any subsystem fails).
- **Format (All OK)**:
  ```json
  {
    "status": "ready",
    "timestamp": "2026-07-16T04:12:08.127164+00:00",
    "checks": {
      "database": true,
      "pending_store": true,
      "execution_framework": true,
      "configuration": true,
      "authentication_subsystem": true,
      "metrics_subsystem": true
    }
  }
  ```
- **Format (Subsystem Failure)**:
  ```json
  {
    "status": "not_ready",
    "timestamp": "2026-07-16T04:15:01.320145+00:00",
    "checks": {
      "database": true,
      "pending_store": false,
      "execution_framework": false,
      "configuration": true,
      "authentication_subsystem": true,
      "metrics_subsystem": true
    }
  }
  ```
