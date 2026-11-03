"""MCP server for guarded tool calls. Approval happens out of band, in host code."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer


def build_server(host, approval=None):
    server = MCPServer("LeanGuard")

    @server.tool(structured_output=True)
    def policy_manifest() -> dict[str, Any]:
        """Describe the compiled policy pack and the actions it covers."""
        return host.engine.manifest

    @server.tool(structured_output=True)
    def available_tools() -> dict[str, Any]:
        """List the underlying tools. Call them only through guarded_call."""
        return host.adapter.tool_schemas()

    @server.tool(structured_output=True)
    def guarded_call(
        action: str, arguments: dict, proposal_id: str | None = None
    ) -> dict[str, Any]:
        """Run an underlying tool if the policy allows it. Lean decides before the tool runs.

        `proposal_id` points to an approval the user already gave. Passing one
        does not grant approval.
        """
        if approval is not None and proposal_id is None and host.adapter.mutating(action):
            proposal = host.prepare(action, arguments)
            host.confirm(proposal.id, approval(proposal))
            proposal_id = proposal.id
        result = host.execute(action, arguments, proposal_id=proposal_id)
        if not result["allow"]:
            return {
                "allow": False,
                "request_id": result["request_id"],
                "message": "Tool call denied by policy.",
            }
        return {
            key: value
            for key, value in result.items()
            if key not in {"reasons", "errors", "evidence"}
        }

    return server
