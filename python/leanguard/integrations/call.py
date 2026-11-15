"""The model-facing entry point shared by framework tools."""

import asyncio
from collections.abc import Callable
from typing import Any


class GuardedCallError(RuntimeError):
    """Model-safe failure; it does not establish whether a dispatch occurred."""


FAILURE_MESSAGE = (
    "Guarded call failed; its outcome may be unknown. Ask the operator; do not retry automatically."
)


def bind_guarded_call(host) -> Callable:
    """Bind a tool to a trusted host (or a bound MultiAgentHost agent).

    Keep the host alive until every invocation has completed. Only the returned
    callable belongs in the agent's tool registry; the host remains trusted.
    """

    def guarded_call(
        action: str, arguments: dict[str, Any], proposal_id: str | None = None
    ) -> dict[str, Any]:
        """Execute a backend tool subject to the compiled policy.

        Args:
            action: Backend action name.
            arguments: Exact arguments for the backend action.
            proposal_id: Reference to a prior human approval, if available.

        Returns:
            Admission status, request ID, and recorded outcome. Unknown outcomes
            require reconciliation; do not retry them automatically.
        """
        if not isinstance(action, str) or not isinstance(arguments, dict):
            raise TypeError("action must be a string and arguments must be an object")
        if proposal_id is not None and not isinstance(proposal_id, str):
            raise TypeError("proposal_id must be a string or null")
        try:
            result = host.execute(action, arguments, proposal_id=proposal_id)
        except Exception:  # noqa: BLE001 -- SDK error messages must not expose trusted diagnostics.
            # SDKs commonly turn exception strings into tool messages. The
            # original context remains available to trusted Python callers.
            raise GuardedCallError(FAILURE_MESSAGE) from None
        if not result["allow"]:
            return {
                "allow": False,
                "request_id": result["request_id"],
                "message": "Tool call denied by policy.",
            }
        # Detailed diagnostics and exception text belong in the trusted journal.
        return {
            key: value
            for key, value in result.items()
            if key not in {"reasons", "errors", "evidence", "error"}
        }

    return guarded_call


def bind_async_guarded_call(host) -> Callable:
    """Bind asynchronous SDK entry points to the complete synchronous transaction."""
    execute = bind_guarded_call(host)

    async def guarded_call(
        action: str, arguments: dict[str, Any], proposal_id: str | None = None
    ) -> dict[str, Any]:
        """Execute a backend tool subject to the compiled policy.

        Args:
            action: Backend action name.
            arguments: Exact arguments for the backend action.
            proposal_id: Reference to a prior human approval, if available.

        Returns:
            Admission status, request ID, and recorded outcome. Unknown outcomes
            require reconciliation; do not retry them automatically.
        """
        task = asyncio.create_task(asyncio.to_thread(execute, action, arguments, proposal_id))
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                # Cancellation cannot stop a synchronous backend. Drain its
                # journal transaction before releasing the owning host.
                cancelled = True
            except Exception:
                if not cancelled:
                    raise
                break
        if cancelled:
            # Retrieve any exception so the completed worker is never orphaned.
            if not task.cancelled():
                task.exception()
            raise asyncio.CancelledError
        return task.result()

    return guarded_call
