"""DSPy ReAct tools backed by LeanGuard."""

from .call import bind_async_guarded_call


def guarded_tool(host):
    """Create an asynchronous DSPy Tool; optimization cannot change policy."""
    from dspy import Tool

    return Tool(bind_async_guarded_call(host))
