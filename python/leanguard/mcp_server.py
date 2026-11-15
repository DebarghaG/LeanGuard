"""MCP server for guarded tool calls. Approval happens out of band, in host code."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from .integrations.call import FAILURE_MESSAGE, GuardedCallError, bind_guarded_call


def build_server(host, approval=None):
    server = MCPServer("LeanGuard")
    execute = bind_guarded_call(host)

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
        try:
            if approval is not None and proposal_id is None and host.adapter.mutating(action):
                proposal = host.prepare(action, arguments)
                host.confirm(proposal.id, approval(proposal))
                proposal_id = proposal.id
        except Exception:  # noqa: BLE001 -- SDK error messages must not expose trusted diagnostics.
            raise GuardedCallError(FAILURE_MESSAGE) from None
        return execute(action, arguments, proposal_id)

    return server
