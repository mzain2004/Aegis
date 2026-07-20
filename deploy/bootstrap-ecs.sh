#!/usr/bin/env bash
# Bootstrap Veto Ops on Alibaba Cloud ECS (Ubuntu 22.04/24.04).
# Create a free-trial or cheap ECS instance, SSH in, clone the repo, then:
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

echo "==> Building and starting Veto Ops proxy + mock MCP"
cd "${REPO_ROOT}"
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build

echo "==> Waiting for health"
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:9000/health" >/dev/null 2>&1; then
    echo "Veto Ops is healthy on :9000"
    curl -fsS "http://127.0.0.1:9000/health" || true
    PUBLIC_IP="$(curl -fsS https://ipv4.icanhazip.com 2>/dev/null || true)"
    echo
    echo "Next:"
    echo "  1) Alibaba ECS security group: allow inbound TCP 22 and (demo) TCP 9000"
    if [[ -n "${PUBLIC_IP}" ]]; then
      echo "  2) Health from outside: curl http://${PUBLIC_IP}:9000/health"
    else
      echo "  2) Health from outside: curl http://<ECS_PUBLIC_IP>:9000/health"
    fi
    echo "  3) Edit deploy/.env secrets (SHARED_HMAC_SECRET, admin key, DASHSCOPE_API_KEY)"
    echo "  4) Restart: docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d"
    echo "  5) Agent on the ECS host: VETO_PROXY_URL=http://127.0.0.1:9000 python -m agent --alert 'demo'"
    exit 0
  fi
  sleep 2
done

echo "Health check timed out. Logs:"
docker compose -f deploy/docker-compose.yml --env-file deploy/.env logs --tail=80
exit 1
