"""Strands tool registration backed by LeanGuard-owned execution."""

from .call import bind_async_guarded_call


def guarded_tool(host):
    """Register the returned tool with Strands instead of the raw backend tools."""
    from strands import tool

    return tool(bind_async_guarded_call(host))
