from __future__ import annotations

import fcntl
import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .engine import Engine, EngineError, canonical, digest
from .types import CallResult, TraceEvent


class ReadOnlyToolError(Exception):
    """Raise from an adapter when a read-only call failed without changing any state.

    Any other exception from a tool is recorded as an unknown outcome.
    """


@dataclass(frozen=True)
class Snapshot:
    resource: str
    revision: str
    facts: dict
    arguments: dict
    amount: int = 0
    units: dict = field(default_factory=dict)


class Adapter(Protocol):
    """The backend interface: snapshot current state and run tools.

    Every writer to the backend must hold `lock`, not only this adapter.
    """

    lock: threading.RLock

    def snapshot(self, action: str, arguments: dict, customer: str) -> Snapshot: ...
    def execute(self, action: str, arguments: dict) -> Any: ...


class IdentityAdapter(Adapter, Protocol):
    """An adapter that works out the customer's identity from backend events.

    `events` are oldest first and already filtered to this principal and session.
    The host trusts whatever identity you return, so derive it only from
    authoritative evidence, never from model output.
    """

    def resolve_identity(self, events: list[TraceEvent]) -> str: ...


@dataclass(frozen=True)
class Proposal:
    id: str
    action: str
    arguments_json: str
    resource: str
    revision: str
    binding: str
    details_json: str

    @property
    def details(self) -> dict:
        return json.loads(self.details_json)


class GuardHost:
    """Runs tool calls through the Lean policy and journals every decision.

    Only one host may write a journal at a time. Give the agent `execute` and
    proposal details; keep `confirm` and `observe_trusted` in trusted UI code.
    Tool output and agent text never count as a confirmation.
    """

    def __init__(
        self,
        domain: str,
        database: Path,
        adapter: Adapter,
        *,
        principal: str,
        session: str,
        binary: Path | None = None,
        clock=None,
    ):
        if not principal or not session:
            raise ValueError("principal and session must be supplied by the host")
        self.domain, self.adapter = domain, adapter
        self.principal, self.session = principal, session
        self.binary, self.clock = binary, clock or (lambda: int(time.time()))
        self._lock = threading.RLock()
        self.database = Path(database).resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        # Held for the object's lifetime; close() releases it.
        self._lockfile = open(str(self.database) + ".lock", "a+b")  # noqa: SIM115
        try:
            fcntl.flock(self._lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._lockfile.close()
            raise RuntimeError("another writer owns this guardrail journal") from None
        try:
            self.db = sqlite3.connect(self.database, isolation_level=None, check_same_thread=False)
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS journal (
                    seq INTEGER PRIMARY KEY, command TEXT NOT NULL, response TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS proposals (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            """)
            self.engine = Engine(domain, binary)
            expected = {"domain": domain, "principal": principal, "engine": self.engine.fingerprint}
            existing = dict(self.db.execute("SELECT key, value FROM metadata"))
            if existing and existing != expected:
                raise RuntimeError("journal identity or compiled policy version mismatch")
            if not existing:
                self.db.executemany("INSERT INTO metadata VALUES (?, ?)", expected.items())
            self._replay()
        except BaseException:
            self.close()
            raise

    def _replay(self):
        for command, response in self.db.execute(
            "SELECT command, response FROM journal ORDER BY seq"
        ):
            actual = self.engine.request(json.loads(command))
            if canonical(actual) != response:
                raise EngineError("journal replay diverged; dispatch disabled")

    def _recover(self):
        self.engine.close()
        self.engine = Engine(self.domain, self.binary)
        try:
            expected = self.db.execute("SELECT value FROM metadata WHERE key='engine'").fetchone()[
                0
            ]
            if self.engine.fingerprint != expected:
                raise EngineError("compiled engine changed; replay requires the pinned binary")
            self._replay()
        except BaseException:
            self.engine.close()
            raise

    def _record(self, command: dict) -> dict:
        command = {"version": self.engine.version, **command}
        self.db.execute("BEGIN IMMEDIATE")
        try:
            response = self.engine.request(command)
            self.db.execute(
                "INSERT INTO journal(command, response) VALUES (?, ?)",
                (canonical(command), canonical(response)),
            )
            self.db.execute("COMMIT")
            return response
        except BaseException:
            # Close the engine first so its speculative state can't be used even if rollback fails.
            self.engine.close()
            self.db.execute("ROLLBACK")
            self._recover()
            raise

    def events(self) -> list[TraceEvent]:
        with self._lock:
            rows = self.db.execute("SELECT command, response FROM journal ORDER BY seq").fetchall()
        events = []
        snapshots = {}
        for command, response in rows:
            command, response = json.loads(command), json.loads(response)
            event = dict(command["event"])
            if command["op"] == "agents_grant":
                grant = command["grant"]
                event.update(
                    actor=grant["actor"],
                    workflow=grant["workflow"],
                    delegation=grant["id"],
                    resource=grant["id"],
                    binding=grant["parent"],
                    output=grant,
                )
            elif command["op"] == "agents_revoke":
                grant = next(
                    old["output"]
                    for old in events
                    if old["kind"] == "agent_grant" and old["resource"] == command["delegation"]
                )
                event.update(
                    actor=grant["actor"],
                    workflow=grant["workflow"],
                    delegation=grant["id"],
                    resource=grant["id"],
                )
            elif command["op"] in {"agents_update", "agents_stream_error", "agents_reconcile"}:
                event["kind"] = {
                    "agents_update": "task_update",
                    "agents_stream_error": "stream_error",
                    "agents_reconcile": "reconciled",
                }[command["op"]]
            if command["op"] == "admit":
                event["input"] = command["arguments"]
                event["facts"] = command["facts"]
                if response["decision"]["allow"]:
                    snapshots[event["id"]] = event["facts"]
            elif "outcome" in command:
                event["output"] = command["outcome"]
                event["facts"] = snapshots[event["id"]]
            events.append(event)
            if command["op"] == "admit" and response["decision"]["allow"]:
                events.append({**event, "kind": "dispatch"})
        return events

    def customer(self) -> str:
        """The trusted subject identity. Named `customer` for backward compatibility."""
        events = [
            event
            for event in self.events()
            if event["principal"] == self.principal and event["session"] == self.session
        ]
        resolver = getattr(self.adapter, "resolve_identity", None)
        if resolver is not None:
            identity = resolver(events)
            if not isinstance(identity, str):
                raise TypeError("identity resolver must return a string")
            return identity
        for event in events:
            if event["kind"] == "identity":
                return event["resource"]
        return ""

    def _event(
        self,
        action: str,
        resource: str,
        binding="",
        amount=0,
        kind="request",
        id=None,
        *,
        scope=None,
    ):
        now = self.clock()
        if type(now) is not int or now < 0:
            raise ValueError("clock must supply nonnegative integer seconds")
        return {
            "id": id or uuid.uuid4().hex,
            "time": now,
            "kind": kind,
            "principal": self.principal,
            "session": self.session,
            "action": action,
            "resource": resource,
            "binding": binding,
            "amount": amount,
            **(scope or {}),
        }

    def prepare(self, action: str, arguments: dict) -> Proposal:
        """Create a proposal for the user to approve. Show its `details` in a trusted UI."""
        return self._prepare(action, arguments)

    def _prepare(self, action: str, arguments: dict, *, scope=None) -> Proposal:
        arguments = json.loads(canonical(arguments))
        with self._lock, self.adapter.lock:
            snapshot = self.adapter.snapshot(action, arguments, self.customer())
            token = uuid.uuid4().hex
            details = {
                "action": action,
                "arguments": arguments,
                "resource": snapshot.resource,
                "revision": snapshot.revision,
                "facts": snapshot.facts,
                "units": snapshot.units,
                "principal": self.principal,
                "session": self.session,
                "domain": self.domain,
                "proposal": token,
                "engine": self.engine.fingerprint,
            }
            if scope:
                details["scope"] = dict(scope)
            proposal = Proposal(
                token,
                action,
                canonical(arguments),
                snapshot.resource,
                snapshot.revision,
                digest(details),
                canonical(details),
            )
            self.db.execute(
                "INSERT INTO proposals VALUES (?, ?)", (token, canonical(proposal.__dict__))
            )
            return proposal

    def _proposal(self, id: str) -> Proposal:
        row = self.db.execute("SELECT payload FROM proposals WHERE id=?", (id,)).fetchone()
        if row is None:
            raise ValueError("unknown proposal")
        proposal = Proposal(**json.loads(row[0]))
        if proposal.details["session"] != self.session:
            raise ValueError("proposal belongs to another conversation")
        return proposal

    def confirm(self, proposal_id: str, accepted: bool):
        """Record the user's answer. Call only from trusted UI, after showing `Proposal.details` unchanged."""
        if type(accepted) is not bool:
            raise ValueError("confirmation requires a Boolean user response")
        with self._lock, self.adapter.lock:
            proposal = self._proposal(proposal_id)
            snapshot = self.adapter.snapshot(
                proposal.action, json.loads(proposal.arguments_json), self.customer()
            )
            if snapshot.revision != proposal.revision:
                raise ValueError("state changed; present a new proposal")
            event = self._event(
                proposal.action,
                proposal.resource,
                proposal.binding,
                kind="confirmed" if accepted else "revoked",
                scope=proposal.details.get("scope"),
            )
            self._record({"op": "observe", "event": event})

    def observe_trusted(self, kind: str, resource: str, *, action: str = "user"):
        """Record a trusted user event, such as identity or stated intent. Never expose this to the agent."""
        if kind not in {
            "identity",
            "compensation_requested",
            "travelling",
            "user_action",
            "user_observation",
        }:
            raise ValueError("not an external observation kind")
        with self._lock:
            self._record({"op": "observe", "event": self._event(action, resource, kind=kind)})

    def execute(
        self,
        action: str,
        arguments: dict,
        *,
        proposal_id: str | None = None,
        request_id: str | None = None,
    ) -> CallResult:
        return self._execute(action, arguments, proposal_id=proposal_id, request_id=request_id)

    def _execute(
        self,
        action: str,
        arguments: dict,
        *,
        proposal_id=None,
        request_id=None,
        scope=None,
    ) -> CallResult:
        arguments = json.loads(canonical(arguments))
        request_id = request_id or uuid.uuid4().hex
        with self._lock, self.adapter.lock:
            snapshot = self.adapter.snapshot(action, arguments, self.customer())
            binding = ""
            if proposal_id is not None:
                proposal = self._proposal(proposal_id)
                if (
                    proposal.action != action
                    or proposal.arguments_json != canonical(arguments)
                    or proposal.revision != snapshot.revision
                    or proposal.resource != snapshot.resource
                    or proposal.details.get("scope", {}) != (scope or {})
                ):
                    return {
                        "allow": False,
                        "reasons": ["stale_or_mismatched_confirmation"],
                        "errors": [],
                        "evidence": [],
                        "request_id": request_id,
                    }
                binding = proposal.binding
            event = self._event(
                action, snapshot.resource, binding, snapshot.amount, id=request_id, scope=scope
            )
            event["input"] = snapshot.arguments
            response = self._record(
                {
                    "op": "admit",
                    "event": event,
                    "arguments": snapshot.arguments,
                    "facts": snapshot.facts,
                }
            )
            decision = {**response["decision"], "request_id": request_id}
            if not decision["allow"]:
                return decision
            try:
                value = self.adapter.execute(action, arguments)
            except ReadOnlyToolError as exc:
                self._record(
                    {
                        "op": "observe",
                        "event": {**event, "time": self.clock(), "kind": "failure"},
                        "outcome": {"error": str(exc)},
                    }
                )
                return {**decision, "outcome": "failure", "error": str(exc)}
            except BaseException as exc:
                # An exception doesn't mean the tool had no effect, so the outcome is unknown.
                self._record(
                    {
                        "op": "observe",
                        "event": {**event, "time": self.clock(), "kind": "unknown"},
                        "outcome": {"error_type": type(exc).__name__},
                    }
                )
                if not isinstance(exc, Exception):
                    raise
                return {**decision, "outcome": "unknown", "error": type(exc).__name__}
            self._record(
                {
                    "op": "observe",
                    "event": {**event, "time": self.clock(), "kind": "success"},
                    "outcome": value,
                }
            )
            return {**decision, "outcome": "success", "result": value}

    def close(self):
        with self._lock:
            if hasattr(self, "engine"):
                self.engine.close()
            if hasattr(self, "db"):
                self.db.close()
            if hasattr(self, "_lockfile") and not self._lockfile.closed:
                fcntl.flock(self._lockfile, fcntl.LOCK_UN)
                self._lockfile.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
