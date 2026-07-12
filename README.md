# Aegis Proxy

Aegis is a Zero-Trust MCP Execution Guard. This repository now contains the migrated proxy implementation: a FastAPI foundation, transparent MCP forwarding, JSON-RPC classification, mutating-request suspension with in-memory pending storage, and an approval endpoint that replays approved requests through the execution framework.

HMAC verification, replay protection, and additional business rules are reserved for later phases.

## Phase 4 Complete

Aegis now suspends mutating MCP requests before they reach Kubernetes.

Capabilities:

✓ MCP request parsing
✓ Tool identification
✓ SHA256 hashing
✓ UUID nonce generation
✓ Pending request storage
✓ TTL support
✓ Read-only passthrough
✓ Mutating request suspension

Not implemented:

- HMAC
- CLI approval tool
- replay protection
- nonce consumption

## Architecture

The project follows a small Clean Architecture layout:

- `app/main.py` bootstraps FastAPI, registers routers, and configures lifespan hooks.
- `app/config.py` owns validated settings and cached configuration loading.
- `app/logger.py` configures structured JSON logging via `structlog`.
- `app/models.py` defines the proxy data contracts.
- `app/crypto.py`, `app/pending_store.py`, `app/rpc_parser.py`, `app/security.py`, and `app/forwarder.py` contain the request-interception pipeline.
- `app/routes/` contains the HTTP surface.
- `tests/` holds the initial test coverage for service health.

## Directory Guide

- `app/` - application package and service wiring
- `app/routes/` - API routers for the proxy and approval surfaces
- `app/utils/` - reserved location for cross-cutting helpers
- `tests/` - pytest-based validation
- `requirements.txt` - runtime and test dependencies
- `Dockerfile` - container image definition
- `.env.example` - documented environment variables
- `pyproject.toml` - tool configuration for formatting, linting, typing, and tests

## Running Locally

From inside the repository root:

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The application exposes:

- `GET /` - service metadata
- `GET /health` - basic health check
- Swagger UI at `/docs`
- ReDoc at `/redoc`

## Docker

Build the image from the repository root:

```bash
docker build -t aegis-proxy .
docker run --rm -p 9000:9000 --env-file .env aegis-proxy
```

The container listens on port `9000`.

## Environment Variables

The service reads the following values:

- `PROXY_HOST` - bind host, default `0.0.0.0`
- `PROXY_PORT` - bind port, default `9000`
- `K8S_MCP_SERVER_URL` - upstream MCP endpoint used by the forwarder, default `http://127.0.0.1:8000`
- `SHARED_HMAC_SECRET` - reserved for future signature verification
- `NONCE_TTL` - reserved nonce lifetime in seconds, default `300`
- `LOG_LEVEL` - logging level, default `INFO`
- `ENVIRONMENT` - deployment environment label, default `development`

Copy `.env.example` to `.env` and adjust values for your local environment.

## Phase 4 Behavior

Read-only and unknown MCP requests continue through the transparent proxy path.
Mutating MCP requests are intercepted, hashed, assigned a UUID nonce, stored in memory, and returned with HTTP 202.

This phase preserves raw request bytes exactly as received and never forwards intercepted mutating requests upstream.

## Future Roadmap

Phase 5 will add the approval workflow and cryptographic guardrails:

- HMAC verification
- `/approve` endpoint logic
- nonce consumption
- replay protection
- releasing suspended requests to the Kubernetes MCP server
