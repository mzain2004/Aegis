"""Veto Ops agentic engine (Engineer 2).

Uses Alibaba Cloud Model Studio's OpenAI-compatible Responses API with
``previous_response_id`` chaining, ``preserve_thinking``, and session cache
headers. Tool traffic is aimed at the Veto Ops execution-guard proxy.
"""

from __future__ import annotations

__version__ = "0.1.0"
