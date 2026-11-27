"""Microsoft Agent Framework function tools."""

from .call import bind_async_guarded_call


def guarded_tool(host):
    """Create a Python function tool with host-owned execution."""
    from agent_framework import tool

    return tool(bind_async_guarded_call(host))
