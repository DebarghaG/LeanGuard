"""Read-only auditing of normalized, oldest-first recorded histories.

Recorded outcomes stay in the history even after a denied call. Nothing is
executed, and no dispatch, consent, identity or missing outcome is filled in.
"""

from collections.abc import Iterable, Iterator, Sequence
from copy import deepcopy

from .engine import Engine, canonical
from .types import AuditResult, TraceEvent

KINDS = {
    "request",
    "dispatch",
    "success",
    "failure",
    "unknown",
    "confirmed",
    "revoked",
    "identity",
    "compensation_requested",
    "travelling",
    "user_action",
    "user_observation",
    "agent_enable",
    "agent_grant",
    "agent_revoke",
    "task_update",
    "stream_error",
    "reconciled",
}


def _validate(event: TraceEvent) -> None:
    for field in ("id", "kind", "principal", "session", "action", "resource", "binding"):
        if not isinstance(event.get(field), str):
            raise TypeError(f"event {field} must be a string")
    if not all(event[field] for field in ("id", "principal", "session", "action")):
        raise ValueError("empty event identity or action")
    if event["kind"] not in KINDS:
        raise ValueError("unsupported event kind; normalize source records explicitly")
    for field in ("time", "amount"):
        if type(event.get(field)) is not int or event[field] < 0:
            raise ValueError(f"event {field} must be a nonnegative integer")
    canonical(event)


def audit(
    engine: Engine,
    request: TraceEvent,
    history: Sequence[TraceEvent] = (),
    *,
    history_complete: bool = True,
    missing_evidence: Sequence[str] = (),
) -> AuditResult:
    """Audit one request against the events before it (oldest first). Changes nothing.

    Use `history_complete` and `missing_evidence` to say what the trace lacks; the
    engine can't tell whether an omitted consent or fact really happened. The
    decision is only as good as the data, so check `assessment` before reading a
    denial as a violation.
    """
    _validate(request)
    if request["kind"] != "request":
        raise ValueError("audit needs a request event")
    previous = 0
    for event in history:
        _validate(event)
        if event["time"] < previous:
            raise ValueError("history must be chronological")
        previous = event["time"]
    if request["time"] < previous:
        raise ValueError("request precedes its history")
    missing = list(missing_evidence)
    if not history_complete:
        missing.append("incomplete_history")
    for field in ("input", "facts"):
        if field not in request:
            missing.append(f"missing_{field}")
        elif not isinstance(request[field], dict):
            raise ValueError(f"request {field} must be an object")
    with engine._lock:
        response = engine.request(
            {
                "op": "audit",
                "version": engine.version,
                "event": request,
                "arguments": request.get("input", {}),
                "facts": request.get("facts", {}),
                "history": list(reversed(history)),
            }
        )
    decision = response["decision"]
    assessment = "allowed" if decision["allow"] else "denied"
    if missing or decision["errors"]:
        assessment = "insufficient_evidence"
    return {
        "request_id": request["id"],
        "decision": decision,
        "rules": response["rules"],
        "assessment": assessment,
        "missing_evidence": missing,
    }


def replay(
    engine: Engine,
    events: Iterable[TraceEvent],
    *,
    history_complete: bool = True,
) -> Iterator[AuditResult]:
    """Yield one audit per recorded request, keeping every event in the history.

    A record may list `missing_evidence` labels; they carry over to every later
    request. `GuardHost.events()` produces records in this format.
    """
    history = []
    missing = []
    for event in events:
        event = deepcopy(event)  # Streaming importers may reuse a mutable record buffer.
        _validate(event)
        if history and event["time"] < history[-1]["time"]:
            raise ValueError("history must be chronological")
        labels = event.get("missing_evidence", [])
        if not isinstance(labels, list) or any(not isinstance(label, str) for label in labels):
            raise ValueError("missing_evidence must be a list of strings")
        missing = list(dict.fromkeys([*missing, *labels]))
        if event["kind"] == "request":
            yield audit(
                engine, event, history, history_complete=history_complete, missing_evidence=missing
            )
        history.append(event)
