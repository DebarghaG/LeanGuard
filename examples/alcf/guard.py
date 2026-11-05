"""Drop-in guard for the pbsMCP conversation loop.

In `run_conversation` of `pbsMCP/src/main.py`, replace the two dispatch
branches with one call:

    payload = await guard.acall(tool_name, arguments)

and build `guard` once, next to the MCP session (see README.md). The host is
synchronous and holds a lock while the tool runs, so it runs in a worker
thread; the adapter calls back into the event loop to reach the MCP server.
"""

from __future__ import annotations

import asyncio
import json
import sys

from leanguard import GuardHost

DENIED = "Tool call denied by policy."


class ThresholdApprover:
    """Approves any mutating call whose node-minutes stay under a cap.

    For a headless demo only. A real deployment shows `proposal.details` to a
    person on a screen the agent cannot reach, and returns their answer.
    """

    def __init__(self, max_node_minutes: int, log=None):
        self.max_node_minutes = max_node_minutes
        self.log = log or (lambda message: print(message, file=sys.stderr))

    def __call__(self, proposal) -> bool:
        details = proposal.details
        minutes = int(details["facts"].get("node_minutes", 0))
        accepted = minutes <= self.max_node_minutes
        verdict = "approved" if accepted else "refused"
        self.log(f"{verdict} {details['action']} {details['arguments']} ({minutes} node-minutes)")
        return accepted


class Guard:
    """Routes every tool call through a `GuardHost`."""

    def __init__(self, host: GuardHost, approve):
        self.host, self.approve = host, approve

    def call(self, name: str, arguments: dict) -> dict:
        proposal_id = None
        if self.host.adapter.mutating(name):
            proposal = self.host.prepare(name, arguments)
            self.host.confirm(proposal.id, bool(self.approve(proposal)))
            proposal_id = proposal.id
        result = self.host.execute(name, arguments, proposal_id=proposal_id)
        if not result["allow"]:
            # The agent learns that it was refused, not why. Reasons stay in the journal.
            return {"success": False, "error": DENIED, "request_id": result["request_id"]}
        if result["outcome"] != "success":
            return {"success": False, "error": result.get("error", result["outcome"])}
        return result["result"]

    async def acall(self, name: str, arguments: str | dict) -> dict:
        if isinstance(arguments, str):
            arguments = json.loads(arguments or "{}")
        return await asyncio.to_thread(self.call, name, arguments)


def unwrap(payload):
    """Undo FastMCP's `{"result": ...}` wrapper around a tool's dict return.

    The PBS server's tools are annotated `Dict[str, Any]`, so the MCP SDK puts
    their return value under a `result` key in `structuredContent`. The
    adapter and `qstat_from_mcp` want the tool's own dict.
    """
    if (
        isinstance(payload, dict)
        and set(payload) == {"result"}
        and isinstance(payload["result"], dict)
    ):
        return payload["result"]
    return payload


def bridge(session, loop, call_mcp_tool, custom_tools, timeout=60):
    """A synchronous `call_tool` for `PBSAdapter` that reaches the MCP session.

    `call_mcp_tool(session, name, arguments_json)` is the coroutine from
    `main.py`; `custom_tools` is its `CUSTOM_TOOLS` table. The host calls this
    from a worker thread while the event loop keeps serving the MCP session,
    so a stalled server fails after `timeout` seconds instead of hanging.
    """

    def call_tool(name, arguments):
        payload = json.dumps(arguments)
        if name in custom_tools:
            return custom_tools[name](payload)
        future = asyncio.run_coroutine_threadsafe(call_mcp_tool(session, name, payload), loop)
        return unwrap(future.result(timeout=timeout))

    return call_tool


def qstat_from_mcp(call_tool, user: str):
    """A `qstat` for `PBSAdapter` built on the PBS MCP server's `list_jobs`.

    The server's `user_filter` is an exact match, and PBS reports owners as
    `user@host`, so filter here instead of asking the server to.
    """

    def qstat():
        result = call_tool("list_jobs", {})
        if not result.get("success", False):
            raise RuntimeError(result.get("error", "list_jobs failed"))
        return [
            job
            for job in result.get("jobs", [])
            if str(job.get("owner", "")).split("@", 1)[0] == user
        ]

    return qstat
