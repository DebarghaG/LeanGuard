# Multi-agent runtime and A2A

When several agents work on one task, say a planner that hands reads to a worker
and buys from a remote service, two things have to hold together. Each agent
should be able to do only what it was delegated, and the agents together should
not be able to spend more than the parent was allowed. `MultiAgentHost` handles
both by running every agent through one coordinator: a single journal (the
durable SQLite log of decisions) that owns identities, delegations, budgets and
task state for the whole workflow.

Agents propose operations; they cannot mint identities, grants, observations or
confirmations. For each proposal, admission (the engine's allow-or-deny decision),
charging every ancestor's budget and reserving the dispatch (recording the call as
in flight) happen in one native transition, committed to SQLite before anything
runs. Network waits happen outside the coordinator lock. A file lock stops a
second process from writing to the same journal, so every worker that shares
authority, budgets or resources has to go through this one coordinator.

## Concepts

`Agent` is a handle that binds a workload actor, a workflow and a delegation to the
coordinator. The principal is still the host-assigned subject and accounting
namespace, so put the tenant in it. Authenticated orchestration decides which
handle a caller gets; role fields in a payload or actor IDs supplied by a user
never authenticate an agent.

`Grant` is delegated authority that can only shrink. A child grant may narrow the
actions, resources, peers, expiry, count and amount limits, and remaining
delegation depth. Every admitted operation charges every ancestor, which is what
stops two siblings from each spending the parent's full budget. A workflow has one
immutable root, so issuing a second root cannot reset its budget, and revoking a
grant cuts off all of its descendants. A grant is a different thing from a user
`Proposal`, which is a one-use approval of a single call.

`Interaction` describes one exact outbound operation together with the resource,
facts and charge that the host derived for it. It says nothing about the remote
side's state revision. Local tools keep using `Snapshot` and the adapter's lock and
revision contract.

Task phases are typed values that do not depend on any protocol. The A2A adapter
maps wire states onto them and scopes ownership of each task and context by peer,
principal, actor, workflow, delegation and resource. `referenceTaskIds` carries no
authority. A send that names only a context must match that context's resource
before it is dispatched. The first receipt accepted for a dispatch fixes its
response kind, task and context, and later receipts cannot point it at another
target, even one owned by the same agent. These bindings live in the native state,
so they survive journal replay and apply to streamed updates and trusted
reconciliation alike.

The code splits along the same lines. `MultiAgent.lean` holds authority, shared
accounting and the generic temporal grant contracts; `A2A.lean` holds wire
normalization and the A2A policies. On the Python side, `multiagent.py` controls
durable execution and `a2a.py` adapts the protocol. Nothing an agent writes and
nothing a remote peer returns can become user approval, identity, a grant, or
authoritative local backend facts.

## Trust boundary

Agent handles are in-process integration objects and give no operating-system
isolation. The runtime has to keep backend credentials and control channels to
itself, and every real tool effect has to pass through it, exactly as the
[adapter contract](guarantees.md) already requires for a single agent. A remote
service outside the runtime is governed only where it exchanges messages with the
runtime; its internal effects need their own integration with the enforcing
runtime.

## LeanLTL contracts

The multi-agent decision is the conjunction of three things: the original compiled
policy, the authority ledger checks, and the temporal history of grants.
`MultiAgent.decision_leanLTL_correct` proves that this decision agrees exactly with
their combined LeanLTL meaning, policy errors included. Separately,
`authorize_correct` proves the declarative authority contract for every ancestor
returned: matching subject and workflow, a permitted action, resource and peer, no
revocation, an unexpired grant (expiry is inclusive), and enough count and amount
left.

For each ancestor, the admission formula is:

```text
within workflow (previous (not revoked since issued))
```

Projection to the workflow happens before the temporal operators, so events from
other workflows cannot shift `previous` or break `since`. A grant has to be issued
earlier in the journal than the admission that uses it, even when the timestamps
are equal. The witness theorems expose that prior grant and the absence of any
revocation at every later position. On top of this, the A2A pack rejects
continuing a terminal task, dispatching the same peer message twice, and sending
while an earlier send is unresolved. Missing or malformed evidence fails closed.

Admission looks backwards over history, but task lifecycles are about what happens
next. `TaskContracts.lean` therefore uses LeanLTL directly on chronological task
traces:

```text
lifecycle = G (for each phase: phase -> Xw valid_next_phase)
completion = F completed
resolution = F (terminal or input_required or auth_required)
```

`terminal_persists` uses LeanLTL's global induction principle to prove that once a
task reaches a terminal phase it stays there, on any finite or infinite trace that
satisfies `lifecycle`. The finite version is written in upstream `LTLf.Formula`
syntax and connected through `LTLf.equisat`; infinite completion uses upstream
`LTL.Formula` and `LTL.equisat`. Weak next (`Xw`) is what makes the last position of
a finite trace work, because it does not require a successor to exist.

Eventual completion is a different matter. A kernel-checked trace in which a task
stays `working` forever satisfies lifecycle safety and violates eventual
completion, so no admission check or finite-prefix verdict can promise that a
remote task finishes. That has to be assumed about the remote peer.

The kernel regression corpus checks 4,681 grant histories against an independent
chronological oracle, and all 512 phase triples against a pairwise terminal-state
oracle through upstream finite-LTL semantics. Integration tests cover native
dispatch, all 64 phase transitions, malformed responses, scope substitution,
replay, concurrent shared budgets, revocation, storage failure and recovery.

These contracts cover the formal inputs and the transitions the runtime enforces.
The Python code, transport authentication, extracting effects from free text, and
the backend's behaviour are assumed.

## Usage

The built-in packs `multiagent.example`, `multiagent.retail`, `multiagent.airline`
and `multiagent.telecom` include the A2A operations. A downstream pack opts in with
`LeanGuard.A2A.withOperations`, and its own requirements still apply. A
`MultiAgentHost` can also govern local tools only, with a pack that has no A2A
operations.

```python
from pathlib import Path
from leanguard import MultiAgentHost
from leanguard.demo import MemoryTools

with MultiAgentHost(
    "multiagent.example", Path("private/workflow.sqlite"), MemoryTools(),
    principal="tenant/alice", session="conversation-1",
) as runtime:
    planner = runtime.grant(
        "planner", workflow="purchase-1", actions=["read", "write"],
        resources=["document"], calls=10, amount=100, expires=2000000000,
    )
    worker = planner.delegate(
        "worker", actions=["read"], resources=["document"], peers=[""],
        calls=5, amount=40, expires=2000000000,
    )
    result = worker.execute("read", {})
```

Keep `runtime.grant`, `runtime.bind`, `runtime.revoke`, `runtime.confirm` and
`runtime.reconcile`, along with native requests and trusted observations, out of
anything an agent can call. Give each worker only the operations its authenticated
routing allows. `Agent.prepare` binds a user approval to that exact actor,
delegation and workflow, as well as to the arguments, resource, revision and
policy that a single-agent approval already covers.

### Talking to remote agents over A2A

Install `.[a2a]` and construct `A2AClient(agent, {peer_id: Peer(...)})` in trusted
runtime code. Each `Peer` has a transport and a profile that returns
`PeerFacts(resource, amount, facts)` for the exact message envelope. The profile is
where the charge comes from: it must validate the structured domain effects and
derive the amount itself, without relying on anything the remote side says in
free text. The profile cannot
rewrite the admitted message. Credentials belong in the host-configured HTTP
client. Peer IDs must name canonical, authenticated endpoints, since routing
aliases for the same peer would otherwise get separate authority and replay
namespaces.

The bundled transport implements the A2A 1.0 HTTP+JSON client subset: Send
Message, Get Task, Cancel Task, Send Streaming Message and Subscribe to Task, for
both direct Messages and stateful Tasks. It has no A2A server, Agent Card
discovery, push notifications or other transport bindings. Those can be added
behind the replaceable `A2ATransport` interface without touching the authority
model or the temporal semantics.

`A2ATransport.stream` returns an `A2AStream` iterator that the caller owns and that
has an asynchronous `aclose` method; an async generator meets that contract. The
client waits for transport cleanup before releasing the coordinator's close fence,
including when validation fails or the call is cancelled. If you stop consuming
`send_stream` or `subscribe` early, await the generator's `aclose()` yourself, or
wrap it in `contextlib.aclosing`.

### Outcomes, failures and reconciliation

`outcome="success"` means the protocol call returned successfully. The remote task
may still be `working`, and `client.task(peer, task_id)` returns the last phase it
reported. Cancelling a task does not roll anything back. Revoking a grant stops new
admissions, but evidence about an operation that was already admitted can still be
recorded.

A send whose outcome is unknown keeps its reservation and its charge, blocks
further sends to the same peer and resource, and is never retried or refunded
automatically. Polling and subscribing to a known task are authorized separately.
Keep the coordinator open until every network operation and stream has finished
or been cancelled. An interrupted stream says nothing about whether the task
failed or was cancelled.

`runtime.reconcile(request_id, receipt)` is how trusted code settles an operation
when an authenticated receipt arrives late or the backend reports the result some
other way. The runtime must establish where the receipt came from and which
request it belongs to without relying on the acting agent. The native checks bind
the receipt to the original dispatch, update its task evidence, and settle the
outstanding reservation. Nothing is redispatched, no authority is created and no
budget is refunded. An operation can be reconciled only once, and grant expiry and
revocation still apply to every later admission.

### Restarts and replay

On restart, the coordinator replays grants, budgets, decisions and task
observations from the journal without dispatching anything. Exact replay is tied
to the compiled executable, so a changed binary needs an explicit journal
migration. The generic trace `audit` and `replay` API reports delegated calls as
insufficient evidence, because authority cannot be reconstructed from an arbitrary
partial list of events; use native journal replay to recover the full multi-agent
state.

Run the deterministic example with:

```sh
.venv/bin/python examples/multiagent/run.py
```
