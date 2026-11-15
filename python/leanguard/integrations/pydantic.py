"""PydanticAI function tools backed by LeanGuard."""

from .call import bind_async_guarded_call


def guarded_tool(host):
    """Create a Tool with no framework retries or implicit approval authority."""
    from pydantic_ai import Tool

    return Tool(bind_async_guarded_call(host), takes_ctx=False, max_retries=0)
