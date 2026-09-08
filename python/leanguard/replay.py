"""Read-only auditing of normalized, chronological recorded histories.

Recorded outcomes advance history even after a denial. No backend is executed and
no dispatch, consent, identity, or missing outcome is inferred or synthesized.
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
    """Audit a request against prior events, oldest first, without changing the monitor.

    `history_complete` and `missing_evidence` describe the caller's evidence coverage;
    the monitor cannot infer whether an omitted consent/fact existed in reality.
    Native decisions are conditional on the supplied data. Inspect `assessment`
    before treating a denial as evidence of a violation in a source trajectory.
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
    """Yield one audit per recorded request. All recorded events remain in history.

    A trace record may carry `missing_evidence`, a list of missing evidence labels;
    this uncertainty is conservatively retained for subsequent requests as well.
    Host.events() supplies the normalized event format, including dispatches/facts.
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
