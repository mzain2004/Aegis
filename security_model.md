# Aegis Security Model

Aegis enforces a defense-in-depth security model to protect infrastructure mutation requests and human approval paths from malicious tampering, side-channel attacks, and credential leakages.

## 1. Cryptographic Security & Hashing

- **Argon2id for API Keys**: API keys are hashed using Argon2id (`argon2-cffi`). Verification utilizes the parameters recommended by modern security standards to ensure resistance to GPU-based attacks and side-channel leakage.
- **SHA256 Payload Fingerprinting**: All mutating infrastructure requests are hashed using SHA-256 to create immutable request fingerprints. Any tampering with the request body between suspended storage and final execution invalidates the request and triggers an alert.
- **HMAC Signatures for Secure Release**: Releases can be authorized using HMAC-SHA256 signatures generated with a shared secret key. This enables automated, cryptographically-secure workflows without exposing raw passwords.

## 2. Timing Attack Prevention

- **Constant-Time Comparison**: Key comparisons (both for API keys and HMAC signatures) utilize constant-time string comparison algorithms (`hmac.compare_digest`). This prevents malicious clients from guessing keys or signatures byte-by-byte using timing analysis.
- **Fallback Verification scan**: If a client provides an API key without a username prefix, Aegis executes key verification scans against registered operators. This fallback scanning guarantees that even key guessing attempts on un-prefixed keys cannot be exploited via response timing differences.

## 3. Replay Protection

- **State Machine Enforcement**: Aegis enforces a single-direction state machine for approval request lifecycles:
  ```
  PENDING ──> APPROVED ──> EXECUTING ──> COMPLETED | FAILED
  ```
- **Atomic State Transitions**: Transitions are executed under database transaction isolation or repository locks. Once a request is claimed for approval (`PENDING` -> `APPROVED`), any duplicate attempt is immediately blocked.
- **Single-use Execution**: Executed requests (`COMPLETED` or `FAILED`) are marked as terminal. They can never be re-approved or re-executed.

## 4. Logging & Audit Trail Hygiene

- **Sensitive Field Suppression**: Aegis explicitly sanitizes logs to prevent accidental leaks. API keys, hashes, and HMAC signatures are stripped or redacted before log serialization.
- **Immutable Audit Events**: The `audit_events` table registers all system activities (e.g. `USER_CREATED`, `APPROVAL_GRANTED`, `CLEANUP_TRIGGERED`) along with the authenticated operator details (`actor` name and `operator_id`).
- **No Cascading Deletion**: Deleting operators sets the `operator_id` on audit and execution logs to `NULL` but preserves the textual `actor` name. This maintains an immutable historical record of who performed what mutation even if the corresponding user account is later removed.
