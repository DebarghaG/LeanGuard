"""smolagents tools; unrestricted CodeAgent execution is not covered."""

from .call import bind_guarded_call


def guarded_tool(host):
    """Create a Tool suitable for a constrained ToolCallingAgent."""
    from smolagents import tool

    return tool(bind_guarded_call(host))
