"""Guarded tools for LangChain agents and LangGraph ToolNode."""

from .call import bind_async_guarded_call, bind_guarded_call


def guarded_tool(host):
    """Create a StructuredTool supporting both invoke and ainvoke."""
    from langchain_core.tools import StructuredTool

    return StructuredTool.from_function(
        func=bind_guarded_call(host), coroutine=bind_async_guarded_call(host)
    )
