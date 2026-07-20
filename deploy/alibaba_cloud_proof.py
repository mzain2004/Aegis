#!/usr/bin/env python3
"""Alibaba Cloud deployment + API proof for Veto Ops.

This file is the submission artifact that demonstrates:
1. Backend hosting on Alibaba Cloud Elastic Compute Service (ECS)
2. Inference via Alibaba Cloud Model Studio / DashScope (Qwen Responses API)

Live ECS health endpoint (Singapore free-trial instance):
  http://43.106.28.134:9000/health
  http://43.106.28.134:9000/

Related implementation:
  - agent/client.py   — OpenAI SDK pointed at DashScope compatible-mode
  - agent/config.py   — DASHSCOPE_API_KEY + dashscope-intl.aliyuncs.com base URL
  - deploy/bootstrap-ecs.sh — Ubuntu ECS bootstrap for Docker Compose
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# 1) Alibaba Cloud ECS — where the Veto Ops backend is deployed
# ---------------------------------------------------------------------------
ALIBABA_ECS = {
    "provider": "Alibaba Cloud Elastic Compute Service (ECS)",
    "region": "ap-southeast-1 (Singapore)",
    "instance_id": "i-t4ngoh2e94td8avk5w2v",
    "instance_type": "ecs.e-c1m4.large",
    "public_ip": "43.106.28.134",
    "os": "Ubuntu 22.04",
    "health_url": "http://43.106.28.134:9000/health",
    "service_url": "http://43.106.28.134:9000/",
}

# ---------------------------------------------------------------------------
# 2) Alibaba Cloud Model Studio / DashScope — Qwen API used by the agent
# ---------------------------------------------------------------------------
# Official OpenAI-compatible Responses API base path on DashScope international.
DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
DASHSCOPE_RESPONSES_URL = f"{DASHSCOPE_BASE_URL}/responses"
QWEN_MODEL = os.environ.get("QWEN_MODEL", "qwen3.7-max")


def build_dashscope_client():  # type: ignore[no-untyped-def]
    """Construct an OpenAI SDK client aimed at Alibaba Cloud DashScope.

    Requires ``DASHSCOPE_API_KEY`` from Alibaba Cloud Model Studio.
    This is the same wiring used by ``agent/client.py`` in production.
    """

    from openai import OpenAI

    api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "DASHSCOPE_API_KEY is required — create one in Alibaba Cloud "
            "Model Studio / DashScope console"
        )

    return OpenAI(
        api_key=api_key,
        base_url=DASHSCOPE_BASE_URL,
        default_headers={"x-dashscope-session-cache": "enable"},
    )


def call_qwen_ping(prompt: str = "Reply with exactly: veto-ops-ok") -> str:
    """Minimal DashScope Responses API call (Alibaba Cloud Qwen)."""

    client = build_dashscope_client()
    response = client.responses.create(
        model=QWEN_MODEL,
        input=prompt,
        store=True,
        extra_body={"preserve_thinking": True},
    )
    text = getattr(response, "output_text", None)
    return (text or "").strip()


def probe_ecs_health(timeout_seconds: float = 10.0) -> dict[str, object]:
    """Hit the public Alibaba ECS health endpoint for the deployed backend."""

    request = urllib.request.Request(
        ALIBABA_ECS["health_url"],
        headers={"User-Agent": "veto-ops-alibaba-proof/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as resp:
            body = resp.read().decode("utf-8")
            return {
                "ok": True,
                "status_code": resp.status,
                "body": json.loads(body) if body.startswith("{") else body,
                "url": ALIBABA_ECS["health_url"],
            }
    except urllib.error.URLError as exc:
        return {"ok": False, "error": str(exc), "url": ALIBABA_ECS["health_url"]}


def main() -> int:
    print("=== Alibaba Cloud ECS deployment ===")
    print(json.dumps(ALIBABA_ECS, indent=2))
    print()
    print("=== ECS health probe ===")
    health = probe_ecs_health()
    print(json.dumps(health, indent=2))
    print()
    print("=== Alibaba Cloud DashScope / Qwen API ===")
    print(f"base_url={DASHSCOPE_BASE_URL}")
    print(f"responses_url={DASHSCOPE_RESPONSES_URL}")
    print(f"model={QWEN_MODEL}")

    if os.environ.get("DASHSCOPE_API_KEY"):
        print()
        print("=== Live DashScope ping ===")
        try:
            print(call_qwen_ping())
        except Exception as exc:  # noqa: BLE001
            print(f"dashscope_call_failed: {exc}", file=sys.stderr)
            return 1
    else:
        print("DASHSCOPE_API_KEY not set — skipping live model call")
        print("Set the key to exercise the Alibaba Model Studio API from this file.")

    return 0 if health.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
