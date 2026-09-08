"""JSON-compatible public results and chronological trace records."""

from typing import Any, Literal, NotRequired, TypedDict


class Decision(TypedDict):
    allow: bool
    reasons: list[str]
    errors: list[str]
    evidence: list[str]


class CallResult(Decision):
    request_id: str
    outcome: NotRequired[Literal["success", "failure", "unknown"]]
    result: NotRequired[Any]
    error: NotRequired[str]


class TraceEvent(TypedDict):
    id: str
    time: int
    kind: str
    principal: str
    session: str
    action: str
    resource: str
    binding: str
    amount: int
    input: NotRequired[dict]
    output: NotRequired[Any]
    facts: NotRequired[dict]
    missing_evidence: NotRequired[list[str]]


class AuditResult(TypedDict):
    request_id: str
    decision: Decision
    rules: dict[str, bool]
    assessment: Literal["allowed", "denied", "insufficient_evidence"]
    missing_evidence: list[str]
