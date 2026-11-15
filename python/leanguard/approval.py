"""Trusted human approval queue for exact host-created proposals."""

import json
import threading

from .host import GuardHost


class ApprovalDesk:
    """Embed beside a trusted host; never expose the operator server to agents.

    Trusted application code prepares proposals (using a bound agent handle for
    delegated calls), then enqueues their IDs. HTTP clients can only review those
    proposals. Approval writes consent to the host journal, never dispatches.
    """

    page = "approval.html"

    def __init__(self, host: GuardHost):
        self.host = host
        self.lock = threading.RLock()
        self.pending: dict[str, str] = {}

    def enqueue(self, proposal_id: str):
        with self.lock:
            proposal = self.host.proposal(proposal_id)
            self.pending[proposal.id] = proposal.binding
            return proposal.id

    def _status(self, proposal):
        events = [event for event in self.host.events() if event.get("binding") == proposal.binding]
        dispatches = [event for event in events if event["kind"] == "dispatch"]
        if dispatches:
            outcomes = [
                event["kind"]
                for event in events
                if event["id"] == dispatches[-1]["id"]
                and event["kind"] in {"success", "failure", "unknown"}
            ]
            return "consumed", outcomes[-1] if outcomes else "unresolved"
        answers = [event["kind"] for event in events if event["kind"] in {"confirmed", "revoked"}]
        return (
            "accepted" if answers[-1] == "confirmed" else "rejected"
        ) if answers else "pending", None

    def state(self):
        proposals = []
        for proposal_id in self.pending:
            proposal = self.host.proposal(proposal_id)
            status, outcome = self._status(proposal)
            proposals.append(
                {
                    "id": proposal.id,
                    "binding": proposal.binding,
                    "action": proposal.action,
                    "details_text": json.dumps(proposal.details, ensure_ascii=False, indent=2),
                    "status": status,
                    "outcome": outcome,
                }
            )
        return {
            "proposals": proposals,
            "principal": self.host.principal,
            "session": self.host.session,
            "domain": self.host.domain,
            "engine_sha256": self.host.engine.fingerprint,
        }

    def action(self, path, payload):
        if path != "/api/answer" or set(payload) != {"proposal", "binding", "accepted"}:
            raise ValueError("Only an exact proposal answer is supported")
        proposal_id = payload["proposal"]
        if not isinstance(proposal_id, str) or proposal_id not in self.pending:
            raise ValueError("Proposal is not in this trusted review queue")
        proposal = self.host.proposal(proposal_id)
        if payload["binding"] != proposal.binding:
            raise ValueError("The answer does not match the displayed proposal")
        if type(payload["accepted"]) is not bool:
            raise TypeError("An explicit Boolean answer is required")
        status, _ = self._status(proposal)
        if status != "pending" and not (status == "accepted" and not payload["accepted"]):
            raise ValueError(
                "This proposal was already answered or consumed; prepare a new proposal"
            )
        self.host.confirm(proposal.id, payload["accepted"])
        return self.state()

    def export(self, _path):
        raise ValueError("Tool approval data is available only in the trusted host journal")
