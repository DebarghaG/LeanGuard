"""One durable authority domain shared by bound agent handles.

Keep the coordinator, grant/revoke APIs, adapter and native control channel in
trusted host code. A handle is an in-process integration API, not an OS sandbox.
Use authenticated routing when exposing handles to other processes.
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
    """Exact outbound operation with host-derived facts and charge.

    This asserts no revision or lock over remote state. Protocol adapters must
    preserve these admitted arguments on the wire.
    """

    action: str
    peer: str
    resource: str
    arguments: dict
    facts: dict
    amount: int = 0


@dataclass(frozen=True)
class Agent:
    """Host-bound actor identity and a native, attenuating delegation."""

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
        """Narrow authority; all ancestors retain shared, cumulative usage."""
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
    """GuardHost with mandatory native delegation on every admitted operation.

    Each instance still has one principal and one writer. All actors that share
    budgets/resources must use this same journal. Separate instances do not
    establish distributed coordination or a shared quota.
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
        """Trusted host authority. Never expose this method as an agent tool."""
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
        """Trusted routing after authentication, including after journal recovery."""
        with self._lock:
            grant = next((g for g in self._status()["grants"] if g["id"] == delegation), None)
            if grant is None:
                raise ValueError("unknown delegation")
            return Agent(self, grant["actor"], grant["workflow"], delegation)

    def revoke(self, delegation: str) -> None:
        """Revoke this grant and, through ancestor checks, all its descendants."""
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
        """Trusted runtime settlement using an authenticated receipt for this request.

        The runtime must independently establish the receipt's provenance and
        request correlation. Agent text is not a receipt. No tool is redispatched,
        no grant is minted, and no count/amount reservation is refunded.
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
