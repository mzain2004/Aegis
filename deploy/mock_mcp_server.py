#!/usr/bin/env python3
"""Minimal HTTP JSON-RPC MCP stub for free-tier Aegis demos.

Not a real Kubernetes server. Enough for smoke-testing proxy classify /
suspend / approve flows when k3s is not installed on a 1c2g ECS trial box.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


READ_ONLY = {
    "kubectl_get",
    "kubectl_describe",
    "kubectl_logs",
    "kubectl_top",
    "kubectl_events",
}
MUTATING = {
    "kubectl_apply",
    "kubectl_create",
    "kubectl_delete",
    "kubectl_patch",
    "kubectl_replace",
    "kubectl_scale",
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        return

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid json"})
            return

        method = payload.get("method")
        req_id = payload.get("id")
        params = payload.get("params") or {}

        if method == "tools/list":
            tools = [
                {"name": name, "description": f"mock {name}"}
                for name in sorted(READ_ONLY | MUTATING)
            ]
            self._json(
                200,
                {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}},
            )
            return

        if method == "tools/call":
            name = params.get("name") if isinstance(params, dict) else None
            arguments = (
                params.get("arguments") if isinstance(params, dict) else {}
            ) or {}
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "ok": True,
                                "mock": True,
                                "tool": name,
                                "arguments": arguments,
                            }
                        ),
                    }
                ]
            }
            self._json(200, {"jsonrpc": "2.0", "id": req_id, "result": result})
            return

        self._json(
            200,
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"method not found: {method}"},
            },
        )

    def _json(self, status: int, body: dict[str, object]) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"mock mcp listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
