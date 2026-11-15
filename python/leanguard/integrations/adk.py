"""Google ADK tools backed by the trusted host."""

from .call import bind_async_guarded_call


def guarded_tool(host):
    """Create an ADK FunctionTool; approvals stay in trusted host code."""
    from google.adk.tools import FunctionTool

    return FunctionTool(bind_async_guarded_call(host))
