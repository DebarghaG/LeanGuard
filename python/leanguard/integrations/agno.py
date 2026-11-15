"""Agno function tools backed by LeanGuard."""

from .call import bind_async_guarded_call


def guarded_tool(host):
    """Create an asynchronous Function; do not enable SDK result caching."""
    from agno.tools.function import Function

    return Function.from_callable(bind_async_guarded_call(host))
