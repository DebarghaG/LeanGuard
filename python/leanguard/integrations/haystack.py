"""Haystack Agent tools (including Haystack 3's invocation API)."""

from .call import bind_async_guarded_call, bind_guarded_call


def guarded_tool(host):
    """Create a Tool with both host-owned invocation modes."""
    from haystack.tools import tool

    result = tool(bind_guarded_call(host))
    result.async_function = bind_async_guarded_call(host)
    return result
