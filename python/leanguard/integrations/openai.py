"""OpenAI function tools; provider-hosted tools are outside this boundary."""

from .call import bind_async_guarded_call


def guarded_tool(host):
    """Create a FunctionTool whose execution is owned by LeanGuard."""
    from agents import function_tool

    # Backend argument objects are intentionally open; their policy schemas are
    # enforced by the compiled pack, not OpenAI's restricted strict-schema form.
    return function_tool(
        bind_async_guarded_call(host), strict_mode=False, failure_error_function=None
    )
