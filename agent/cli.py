"""CLI entrypoint for the Veto Ops agent."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from agent.config import get_agent_settings
from agent.loop import VetoOpsAgent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the Veto Ops agent against the Veto Ops MCP execution guard "
            "using the DashScope Responses API."
        )
    )
    parser.add_argument(
        "--alert",
        required=True,
        help="Alert / incident context passed to the agent as the first user turn.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the run result as JSON instead of plain text.",
    )
    return parser


async def _async_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_agent_settings()

    try:
        async with VetoOpsAgent(settings=settings) as agent:
            result = await agent.run_incident(args.alert)
    except ValueError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"agent run failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    "final_text": result.final_text,
                    "response_ids": result.response_ids,
                    "turn_count": result.turn_count,
                    "pending_approvals": result.pending_approvals,
                    "stopped_reason": result.stopped_reason,
                    "model": settings.qwen_model,
                    "tool_mode": settings.tool_mode,
                    "veto_proxy_url": settings.veto_proxy_url,
                },
                indent=2,
            )
        )
    else:
        print(result.final_text)
        if result.pending_approvals:
            print(
                "\nPending Veto Ops approval nonces: "
                + ", ".join(result.pending_approvals),
                file=sys.stderr,
            )

    return 0


def main(argv: list[str] | None = None) -> None:
    raise SystemExit(asyncio.run(_async_main(argv)))


if __name__ == "__main__":
    main()
