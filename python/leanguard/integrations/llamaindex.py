"""LlamaIndex function tools with synchronous and asynchronous entry points."""

from .call import bind_async_guarded_call, bind_guarded_call


def guarded_tool(host):
    """Create a FunctionTool; keep raw backend functions out of the agent."""
    from llama_index.core.tools import FunctionTool

    return FunctionTool.from_defaults(
        fn=bind_guarded_call(host), async_fn=bind_async_guarded_call(host)
    )
