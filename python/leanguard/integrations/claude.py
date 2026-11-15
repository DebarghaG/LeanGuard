"""In-process MCP tools for Claude Agent SDK."""

from ..engine import canonical
from .call import bind_async_guarded_call


def guarded_tool(host):
    """Create an SDK MCP tool; expose only this tool in allowed_tools."""
    from claude_agent_sdk import tool

    execute = bind_async_guarded_call(host)

    @tool(
        "guarded_call",
        "Execute a backend action through LeanGuard. Approval is supplied by trusted human UI.",
        {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "arguments": {"type": "object"},
                "proposal_id": {"type": ["string", "null"]},
            },
            "required": ["action", "arguments"],
            "additionalProperties": False,
        },
    )
    async def guarded_call(arguments):
        result = await execute(**arguments)
        return {"content": [{"type": "text", "text": canonical(result)}]}

    return guarded_call
