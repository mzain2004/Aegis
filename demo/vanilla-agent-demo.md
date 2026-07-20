# Vanilla MCP agent demo

This note documents the intentionally unprotected path for the demo. The vanilla agent should be pointed at the real Kubernetes MCP server so that mutating actions bypass the Aegis guard and execute directly.

Suggested sequence:
1. Start the real MCP endpoint.
2. Point the vanilla agent at it.
3. Trigger a mutating action such as a deployment patch or rollout restart.
4. Observe that the action is permitted without the human approval challenge.
