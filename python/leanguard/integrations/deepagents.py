"""Reuse LangChain's guarded tool in Deep Agents.

Coverage is limited to this registered tool. Built-in shell, filesystem, browser,
and subagent tools require their own deployment restrictions.
"""

from .langchain import guarded_tool

__all__ = ["guarded_tool"]
