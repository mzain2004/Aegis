# Aegis Production Checklist

Verify the following configurations, security controls, and telemetry endpoints prior to production deployment.

## Telemetry & Metrics Verification
- [ ] Prometheus metrics endpoint (`/metrics`) is active and scraping.
- [ ] Uptime, latency, and database query durations are monitored.
- [ ] Alerting thresholds configured for `authentication_failure` rates.

## Security & Verification
- [ ] Nonce and replay protection checks are enabled.
- [ ] Sensitive headers (like cookies, authorization tokens) are redacted in audit logging.
- [ ] The `shared_hmac_secret` setting is changed from its default value.
- [ ] Operator API keys are rotated and managed securely.

## Operational Setup
- [ ] The database cleanup scheduler is started.
- [ ] `AUDIT_RETENTION_DAYS` is set to meet your organizational compliance goals.
- [ ] Ready (`/ready`) and live (`/live`) probes are configured in the Kubernetes deployment manifest.
