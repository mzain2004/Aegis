#!/usr/bin/env bash
set -euo pipefail

nonce="${1:-}"
if [[ -z "$nonce" ]]; then
  echo "Usage: $0 <nonce> [proxy-url]" >&2
  exit 2
fi

proxy_url="${2:-http://127.0.0.1:9000/approve/}"
secret="${SHARED_HMAC_SECRET:-development-shared-secret}"

if ! command -v openssl >/dev/null 2>&1; then
  echo "OpenSSL is required but was not found on PATH." >&2
  exit 127
fi

signature="$(printf '%s' "$nonce" | openssl dgst -sha256 -hmac "$secret" -hex | awk '{print $2}')"

curl -fsS -X POST "$proxy_url" \
  -H 'Content-Type: application/json' \
  -d "{\"nonce\":\"$nonce\",\"signature\":\"$signature\"}"
