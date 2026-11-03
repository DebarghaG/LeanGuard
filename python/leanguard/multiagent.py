"""Multi-agent runtime: agent handles share one durable journal, grants and budgets.

Keep the coordinator, grant and revoke calls, the adapter and the native engine in
trusted host code. Handles are ordinary Python objects with no process isolation;
put authenticated routing in front of them before exposing them to other processes.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from .engine import canonical
from .host import GuardHost, Proposal
from .types import CallResult


@dataclass(frozen=True)
class Interaction:
    """An outbound operation, with resource, facts and charge worked out by the host.

    Unlike a `Snapshot` it has no revision, because the host can't lock remote
    state. Protocol adapters must send exactly the admitted arguments.
    """

    action: str
    peer: str
    resource: str
    arguments: dict
    facts: dict
    amount: int = 0


@dataclass(frozen=True)
class Agent:
    """An agent handle: an actor identity bound by the host, plus its delegated grant."""

    _host: MultiAgentHost
    actor: str
    workflow: str
    delegation: str

    def _scope(self, peer="") -> dict:
        return {
            "actor": self.actor,
            "workflow": self.workflow,
            "delegation": self.delegation,
            "peer": peer,
        }

    def execute(
        self, action: str, arguments: dict, *, proposal_id=None, request_id=None
    ) -> CallResult:
        return self._host._execute(
            action, arguments, proposal_id=proposal_id, request_id=request_id, scope=self._scope()
        )

    def prepare(self, action: str, arguments: dict) -> Proposal:
        return self._host._prepare(action, arguments, scope=self._scope())

    def delegate(
        self,
        actor: str,
        *,
        actions: list[str],
        resources: list[str],
        peers: list[str],
        calls: int,
        amount: int,
        expires: int,
        depth: int = 0,
    ) -> Agent:
        """Create a child grant with narrower authority. Its usage also counts against every ancestor."""
        return self._host._grant(
            actor,
            workflow=self.workflow,
            actions=actions,
            resources=resources,
            peers=peers,
            calls=calls,
            amount=amount,
            expires=expires,
            depth=depth,
            parent=self.delegation,
            issuer=self.actor,
        )


class MultiAgentHost(GuardHost):
    """A GuardHost in which every operation must also be covered by a delegated grant.

    Each instance has one principal and one writer. Agents that share budgets or
    resources must use the same instance; separate instances share nothing.
    """

    def __init__(self, *args, **kwargs):
        self._pending_interactions = set()
        super().__init__(*args, **kwargs)
        try:
            with self._lock:
                status = self._status()
                if not status["enabled"]:
                    self._record(
                        {
                            "op": "agents_enable",
                            "event": self._event("agents.enable", "authority", kind="agent_enable"),
                        }
                    )
        except BaseException:
            self.close()
            raise

    def _status(self) -> dict:
        return self.engine.request(
            {
                "op": "agents_status",
                "version": self.engine.version,
                "event": self._event("agents.status", "authority"),
            }
        )["agents"]

    def grant(
        self,
        actor: str,
        *,
        workflow: str,
        actions: list[str],
        resources: list[str],
        peers: list[str] | None = None,
        calls: int,
        amount: int,
        expires: int,
        depth: int = 4,
    ) -> Agent:
        """Issue a root grant for a workflow. Host code only; never expose this to an agent."""
        return self._grant(
            actor,
            workflow=workflow,
            actions=actions,
            resources=resources,
            peers=[""] if peers is None else peers,
            calls=calls,
            amount=amount,
            expires=expires,
            depth=depth,
            parent="",
            issuer="",
        )

    def _grant(
        self,
        actor,
        *,
        workflow,
        actions,
        resources,
        peers,
        calls,
        amount,
        expires,
        depth,
        parent,
        issuer,
    ) -> Agent:
        for value in (calls, amount, expires, depth):
            if type(value) is not int or value < 0:
                raise ValueError("delegation bounds must be nonnegative integers")
        grant = {
            "id": uuid.uuid4().hex,
            "parent": parent,
            "principal": self.principal,
            "actor": actor,
            "workflow": workflow,
            "actions": list(actions),
            "resources": list(resources),
            "peers": list(peers),
            "calls": calls,
            "amount": amount,
            "expires": expires,
            "depth": depth,
        }
        with self._lock:
            self._record(
                {
                    "op": "agents_grant",
                    "grant": grant,
                    "issuer": issuer,
                    "event": self._event("agents.grant", grant["id"], kind="agent_grant"),
                }
            )
        return Agent(self, actor, workflow, grant["id"])

    def bind(self, delegation: str) -> Agent:
        """Get the handle for an existing grant, e.g. after authenticating a worker or reopening the journal."""
        with self._lock:
            grant = next((g for g in self._status()["grants"] if g["id"] == delegation), None)
            if grant is None:
                raise ValueError("unknown delegation")
            return Agent(self, grant["actor"], grant["workflow"], delegation)

    def revoke(self, delegation: str) -> None:
        """Revoke a grant. Its descendants stop working too, since admission checks every ancestor."""
        with self._lock:
            self._record(
                {
                    "op": "agents_revoke",
                    "delegation": delegation,
                    "event": self._event("agents.revoke", delegation, kind="agent_revoke"),
                }
            )

    def task(self, agent: Agent, peer: str, task_id: str) -> dict:
        with self._lock:
            task = next(
                (
                    t
                    for t in self._status()["tasks"]
                    if t["peer"] == peer
                    and t["id"] == task_id
                    and t["actor"] == agent.actor
                    and t["delegation"] == agent.delegation
                    and t["workflow"] == agent.workflow
                ),
                None,
            )
            if task is None:
                raise ValueError("unknown or inaccessible task")
            return task

    def reconcile(self, request_id: str, receipt: dict) -> None:
        """Settle an unresolved request using an authenticated receipt.

        Check yourself that the receipt is authentic and belongs to this request;
        agent text never qualifies. Nothing is redispatched, no grant is created,
        and the reserved count and amount are not refunded.
        """
        receipt = json.loads(canonical(receipt))
        with self._lock:
            if request_id in self._pending_interactions:
                raise ValueError("finish or cancel the active operation before reconciling it")
            dispatch = next(
                (e for e in self.events() if e["id"] == request_id and e["kind"] == "dispatch"),
                None,
            )
            if dispatch is None:
                raise ValueError("unknown dispatch")
            self._record(
                {
                    "op": "agents_reconcile",
                    "event": {**dispatch, "time": self.clock()},
                    "outcome": receipt,
                }
            )

    def _begin_interaction(self, agent: Agent, interaction: Interaction):
        with self._lock:
            event = self._event(
                interaction.action,
                interaction.resource,
                amount=interaction.amount,
                scope=agent._scope(interaction.peer),
            )
            event["input"] = json.loads(canonical(interaction.arguments))
            response = self._record(
                {
                    "op": "admit",
                    "event": event,
                    "arguments": event["input"],
                    "facts": interaction.facts,
                }
            )
            if response["decision"]["allow"]:
                self._pending_interactions.add(event["id"])
            return event, {**response["decision"], "request_id": event["id"]}

    def _release_interaction(self, event):
        with self._lock:
            self._pending_interactions.discard(event["id"])

    def close(self):
        with self._lock:
            if self._pending_interactions:
                raise RuntimeError("finish or cancel active A2A operations before closing the host")
            super().close()

    def _update_interaction(self, event, output):
        with self._lock:
            self._record(
                {
                    "op": "agents_update",
                    "event": {**event, "time": self.clock()},
                    "outcome": output,
                }
            )

    def _finish_interaction(self, event, output, *, unknown=False):
        with self._lock:
            self._record(
                {
                    "op": "observe",
                    "event": {
                        **event,
                        "kind": "unknown" if unknown else "success",
                        "time": self.clock(),
                    },
                    "outcome": output,
                }
            )

    def _stream_error(self, event, error_type):
        with self._lock:
            self._record(
                {
                    "op": "agents_stream_error",
                    "event": {**event, "time": self.clock()},
                    "outcome": {"error_type": error_type},
                }
            )
