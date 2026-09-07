"""MCP entry point. Approval remains a host-controlled, out-of-band capability."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer


def build_server(host, approval=None):
    server = MCPServer("LeanGuard")

    @server.tool(structured_output=True)
    def policy_manifest() -> dict[str, Any]:
        """Describe the compiled native Lean policy pack and covered actions."""
        return host.engine.manifest

    @server.tool(structured_output=True)
    def available_tools() -> dict[str, Any]:
        """Describe the underlying tools; all calls must pass through guarded_call."""
        return host.adapter.tool_schemas()

    @server.tool(structured_output=True)
    def guarded_call(
        action: str, arguments: dict, proposal_id: str | None = None
    ) -> dict[str, Any]:
        """Propose an underlying tool call. Lean authorizes before any tool execution.

        A proposal ID only refers to an existing approval; it does not grant one.
        """
        if approval is not None and proposal_id is None and host.adapter.mutating(action):
            proposal = host.prepare(action, arguments)
            host.confirm(proposal.id, approval(proposal))
            proposal_id = proposal.id
        return host.execute(action, arguments, proposal_id=proposal_id)

    return server
