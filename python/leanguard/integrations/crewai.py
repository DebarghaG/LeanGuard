"""CrewAI tools backed by LeanGuard."""

from .call import bind_guarded_call


def guarded_tool(host):
    """Create a synchronous CrewAI tool without result caching."""
    from crewai.tools import tool

    result = tool(bind_guarded_call(host))
    result.cache_function = lambda arguments, result: False
    return result
