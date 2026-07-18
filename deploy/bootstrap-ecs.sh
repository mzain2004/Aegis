#!/usr/bin/env bash
# Bootstrap Aegis on a free/cheap Alibaba Cloud ECS (Ubuntu 22.04/24.04).
# Run as root or with sudo from a cloned Aegis repo:
#   sudo bash deploy/bootstrap-ecs.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="${REPO_ROOT}/deploy"

echo "==> Installing Docker Engine + Compose plugin"
if ! command -v docker >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  . /etc/os-release
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
  systemctl enable --now docker
fi

if [[ ! -f "${DEPLOY_DIR}/.env" ]]; then
  cp "${DEPLOY_DIR}/env.example" "${DEPLOY_DIR}/.env"
  echo "==> Created deploy/.env from env.example — edit secrets before public use"
fi

echo "==> Building and starting Aegis + mock MCP"
cd "${REPO_ROOT}"
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build

echo "==> Waiting for health"
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:9000/health" >/dev/null 2>&1; then
    echo "Aegis is healthy on :9000"
    curl -fsS "http://127.0.0.1:9000/health" || true
    echo
    echo "Next:"
    echo "  1) Open Alibaba ECS security group: inbound TCP 9000 (demo only)"
    echo "  2) Edit deploy/.env secrets (SHARED_HMAC_SECRET, admin key, DASHSCOPE_API_KEY)"
    echo "  3) Restart: docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d"
    echo "  4) Agent from host: AEGIS_PROXY_URL=http://127.0.0.1:9000 python -m agent --alert 'demo'"
    exit 0
  fi
  sleep 2
done

echo "Health check timed out. Logs:"
docker compose -f deploy/docker-compose.yml --env-file deploy/.env logs --tail=80
exit 1
