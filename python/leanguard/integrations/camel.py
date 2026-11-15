"""CAMEL FunctionTool registration backed by LeanGuard."""

from .call import bind_async_guarded_call


def guarded_tool(host):
    """Create an asynchronous tool; unrestricted code tools remain excluded."""
    from camel.toolkits import FunctionTool

    return FunctionTool(bind_async_guarded_call(host))
