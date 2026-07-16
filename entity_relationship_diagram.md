# Entity Relationship Diagram

This document contains the Entity Relationship (ER) diagram for the Aegis persistence layer.

```mermaid
erDiagram
    PENDING_REQUESTS {
        string id PK
        string approval_id UK
        string nonce UK
        string payload_hash
        string tool
        string operation
        string namespace
        string resource
        blob raw_payload
        json headers
        string status
        datetime created_at
        datetime expires_at
        datetime approved_at
        datetime completed_at
        datetime failed_at
        string approved_by
        string execution_backend
        integer retry_count
    }

    APPROVAL_RECORDS {
        string id PK
        string approval_id FK
        string operator
        boolean signature_verified
        string ip_address
        string user_agent
        datetime recorded_at
    }

    EXECUTION_RECORDS {
        string execution_id PK
        string approval_id FK
        string status
        string backend
        datetime started_at
        datetime completed_at
        integer duration_ms
        integer status_code
        string error_type
        boolean retryable
    }

    AUDIT_EVENTS {
        string event_id PK
        string event_type INDEX
        string actor
        datetime recorded_at
        json details
    }

    PENDING_REQUESTS ||--o| APPROVAL_RECORDS : "claims / approves"
    PENDING_REQUESTS ||--o| EXECUTION_RECORDS : "records run of"
```

## Relationships
- **PendingRequests to ApprovalRecords (1:0..1)**: A pending request optionally has exactly one approval record once claimed and approved by an operator.
- **PendingRequests to ExecutionRecords (1:0..1)**: An approved request has an execution record mapping the execution run details, latency, status code, and errors.
- **AuditEvents (Independent)**: Audit events are immutable, append-only records log-structured to record all transitions and actions within the gateway.
