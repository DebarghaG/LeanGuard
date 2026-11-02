# Multi-agent runtime and A2A

The trusted runtime owns one authoritative coordinator journal. Agents submit
proposals; they cannot mint identities, grants, observations, or confirmations.
All workers that share authority, budgets, or resources use that coordinator.
Admission, ancestor budget consumption, and dispatch reservation are one native
transition, committed to SQLite before dispatch. Network waits occur outside the
coordinator lock. The existing file lock rejects competing journal writers.

## Abstractions and trust

- `Agent` binds a workload actor, workflow and delegation to a coordinator. The
  principal remains the host-assigned subject/accounting namespace. Include the
  tenant in that namespace. Authenticated orchestration chooses the handle;
  payload roles and user-supplied actor IDs do not authenticate an agent.
- `Grant` is attenuating authority, distinct from a one-use user `Proposal`.
  Children can narrow actions, resources, peers, expiry, limits and delegation
  depth. Every admitted operation charges every ancestor. Siblings cannot each
  spend the parent's full budget. Each workflow has one immutable root; issuing
  another root cannot reset its budget. Revocation reaches every descendant.
- `Interaction` describes an exact outbound operation and its host-derived resource,
  facts and charge. It makes no claim about a remote state revision. Local tools
  continue to use `Snapshot` and the adapter's backend lock/revision contract.
- Task phases are protocol-independent typed values. The A2A adapter normalizes
  wire states and scopes task/context ownership by peer, principal, actor,
  workflow, delegation and resource. `referenceTaskIds` is not an authority chain.
  Context-only sends must match the context's resource before dispatch. Each
  dispatch's first accepted receipt fixes its response kind, task and context;
  subsequent receipts cannot substitute another target, even one owned by the
  same agent. These native bindings survive journal replay and apply equally to
  streamed updates and trusted reconciliation.

The native module `MultiAgent.lean` contains authority, shared accounting and
generic temporal grant contracts. `A2A.lean` contains wire normalization and A2A
policies. Python `multiagent.py` controls durable execution; `a2a.py` adapts the
protocol. Neither an agent's text nor a remote artifact becomes user approval,
identity, a grant, or authoritative local backend facts.

Agent handles are integration objects, not an OS sandbox. The runtime must retain
backend credentials and control channels, and all actual tool effects must pass
through it, as required by the existing adapter contract. A remote service outside
that runtime is governed at the exchange boundary; its internal effects require
its own integration with the enforcing runtime.

## LeanLTL contracts

The actual multi-agent decision conjoins the original compiled policy, authority
ledger checks and temporal grant history. `MultiAgent.decision_leanLTL_correct`
proves exact agreement with their composed LeanLTL meaning, including policy
errors. `authorize_correct` independently proves the declarative authority contract
for every returned ancestor: subject/workflow, permitted action/resource/peer,
non-revocation, inclusive expiry, and available count/amount bounds.

For each ancestor, the admission formula is:

```text
within workflow (previous (not revoked since issued))
```

Projection happens before the temporal operators. Grant issuance must precede
admission in the journal, even when timestamps are equal. The witness theorems
expose a prior grant and absence of revocation at every subsequent position.
The A2A pack additionally rejects terminal-task continuation, duplicate peer/message
dispatch and unresolved sends. Missing or malformed evidence fails closed.

`TaskContracts.lean` also uses LeanLTL directly on chronological task traces:

```text
lifecycle = G (for each phase: phase -> Xw valid_next_phase)
completion = F completed
resolution = F (terminal or input_required or auth_required)
```

`terminal_persists` uses LeanLTL's global induction principle to prove that a
terminal phase is absorbing on finite and infinite traces satisfying lifecycle.
The finite syntax is upstream `LTLf.Formula`, connected by `LTLf.equisat`; the
infinite completion syntax uses upstream `LTL.Formula` and `LTL.equisat`.
Weak next handles the last position of a finite trace; it does not invent a
successor. A kernel-checked infinite `working` trace satisfies lifecycle safety
and violates eventual completion. Eventual remote progress is an additional
assumption, not a consequence of admission or a finite-prefix verdict.

The kernel regression corpus checks 4,681 grant histories against an independent
chronological oracle, and all 512 phase triples against a pairwise terminal-state
oracle through upstream finite-LTL semantics. Integration tests exercise native
dispatch, all 64 phase transitions, malformed responses, scope substitution,
replay, concurrent shared budgets, revocation, storage failure and recovery.

These are contracts about the formal inputs and enforced transitions. They do not
prove Python, transport authentication, the extraction of declared effects from
free text, backend fidelity, or a complete refinement of distributed execution.

## Usage

Use a `multiagent.example`, `multiagent.retail`, `multiagent.airline`, or
`multiagent.telecom` pack for the built-in A2A surface. Downstream packs opt in
with `LeanGuard.A2A.withOperations`; custom requirements still apply. A
`MultiAgentHost` can also govern local tools using a pack without A2A operations.

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

Keep `runtime.grant`, `runtime.bind`, `runtime.revoke`, `runtime.confirm`, `runtime.reconcile`, native
requests and trusted observations out of the agent-facing surface. Only give
workers the operations permitted by their authenticated runtime routing.
`Agent.prepare` binds user approval to that exact actor/delegation/workflow, in
addition to the existing argument, resource, revision and policy binding.

For A2A, install `.[a2a]` and construct `A2AClient(agent, {peer_id: Peer(...)})`
in trusted runtime code. Each `Peer` has a transport and a profile returning
`PeerFacts(resource, amount, facts)` for the exact envelope. That profile must
validate structured domain effects and derive the charge; a free-text promise
of a spending limit does not establish its effect. The profile cannot rewrite
the admitted message. Credentials stay in the host-configured HTTP client.
Peer IDs must denote canonical authenticated endpoint identities; routing aliases
must not create independent authority/replay namespaces for the same peer.

The provided transport implements the A2A **1.0 HTTP+JSON client** subset:
Send Message, Get Task, Cancel Task, Send Streaming Message and Subscribe to Task.
It supports both direct Messages and stateful Tasks. It does not implement an
A2A server, Agent Card discovery, push notifications, or other transport bindings.
The replaceable `A2ATransport` interface accommodates those integrations without
changing the authority model or temporal semantics.

`outcome="success"` means the protocol operation returned successfully. The
remote task may still be `working`; `client.task(peer, task_id)` returns its last
reported phase. Cancellation does not imply rollback. Revocation prevents new
admissions; evidence for an already admitted operation can still be recorded.

Unknown sends retain their reservation and charge, block another send to the
same peer/resource, and are never automatically retried or refunded. Polling
and subscription to a known task remain separately authorized. The coordinator
must remain open until active network operations/streams finish or are canceled.
An interrupted stream does not imply task failure or cancellation.

`runtime.reconcile(request_id, receipt)` is a trusted coordinator operation for a
late authenticated receipt or backend reconciliation result. The runtime must
establish its provenance and correlation independently of the acting agent.
Native checks bind it to the original dispatch, update its task evidence, and
settle the unresolved reservation without redispatch, new authority, or a budget
refund. Already settled operations cannot be reconciled again. Grant expiry and
revocation still apply to every subsequent admission.

Journal restart replays grants, budgets, decisions and task observations without
dispatch. Exact replay is pinned to the compiled executable. The generic trace
`audit`/`replay` API explicitly reports insufficient evidence for delegated calls;
it cannot reconstruct authority from an arbitrary partial event list. Use native
journal replay for the complete multi-agent state. Existing journals need an
explicit migration when the compiled binary changes.

Run the deterministic example with:

```sh
.venv/bin/python examples/multiagent/run.py
```
