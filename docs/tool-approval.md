# Trusted tool-call approval screen

The approval screen reviews a single host-created proposal. It is separate from
policy-pack review and uses the existing `GuardHost.confirm` authority. It never
dispatches a tool or changes a policy decision.

```python
import threading
from leanguard.approval import ApprovalDesk
from leanguard.workbench import OperatorServer

# host is an existing, trusted GuardHost owned by this application.
desk = ApprovalDesk(host)
proposal = host.prepare("write", {"value": "review this exact text"})
desk.enqueue(proposal.id)
with OperatorServer(desk) as server:
    print(server.url)  # Show only to the authenticated local operator.
    server.serve_forever()
```

In an existing application, run `serve_forever` in an application-managed thread,
call `shutdown` before closing the host, and keep the server and host out of agent
reach. Trusted orchestration prepares proposals and enqueues IDs; there is no HTTP
endpoint to create, change or enqueue proposals. Give agents only the guarded
execution tool. For a delegated call, use `agent.prepare(...)` on the bound handle
and enqueue that proposal on the coordinator's desk. Actor/workflow/delegation
bindings remain in the exact proposal and are checked again during execution.

The screen displays original arguments, resource, authoritative revision, facts,
units, principal, session, executable identity and any agent scope. It preserves
large integers as exact JSON text and renders all proposal content as escaped
text. It does not interpret agent prose as consent. `GuardHost.proposal(id)` reads
the persisted proposal and rejects IDs from another conversation.

Approve records a native confirmation; Reject records a revocation. Accepted
proposals can be revoked before dispatch. A repeated answer or consumed approval
requires a new proposal. The host rechecks backend revision at confirmation and
the full argument/state/authority binding at execution. Policy expiry still
applies. Consent cannot override a missing observation, quota or other native
denial. No automatic retry follows an error.

Refresh reads status from the durable host journal. Dispatched approvals are
shown as consumed, with success, failure, unknown or unresolved outcome. Unknown
does not mean no effect; reconciliation remains a separate trusted workflow.
Restarting the UI does not reset consent: trusted code can enqueue the same ID
and recover its status from the journal. Queue membership itself is in memory.

The same loopback capability, exact Host/Origin checks and authenticated mutation
controls as the [policy workbench](workbench.md) apply. Simultaneous apps have
separate cookies. This is a local operator capability, not a multi-tenant identity
provider; the application's authenticated routing and filesystem/process isolation
remain deployment assumptions. Consent events are journaled by the host under its
bound principal/session. No claim of remote human identity authentication is made.

Tests exercise actual native approval binding, changed state, revocation,
consumption, unknown outcomes, delegated actors, missing prerequisites, and zero
dispatch on approval. Browser checks cover exact numeric display, escaped tool
text, accept/revoke controls and automated accessibility.
