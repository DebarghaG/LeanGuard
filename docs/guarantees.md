# Guarantee boundary

## Kernel-checked statements

| Statement | What it establishes |
|---|---|
| `evaluate_correct` | Boolean temporal evaluation equals the separate `Holds` semantics |
| `project_membership`, `project_idempotent` | Explicit scope projection selects exactly matching keys and is stable |
| `authorized_requirement`, `authorized_no_forbid` | Allow cannot bypass a mandatory rule or an applicable true forbid |
| `decision_sound`, `decision_no_errors` | The actual decision's allow bit implies native authorization and an empty error list |
| `confirmation_has_witness`, `confirmation_not_consumed` | The actual confirmation formula requires a prior matching witness and no matching prior dispatch |
| `confirmedWithin_preserves`, `confirmedWithin_recent_witness` | Adding expiry preserves the one-use guard and requires an in-window confirmation witness |
| `query_membership`, `query_window` | A query selects exactly its matching events, all within its inclusive non-future window |
| `distinct_membership`, `distinct_duplicate` | Deduplication preserves value membership and a duplicate value does not change the result |
| `quota_reservation_bound` | Inserting the new dispatch after a successful quota check preserves its count and amount bounds |
| `reservation_retained`, `deny_no_reservation` | The reservation operation adds a dispatch only on allow |
| `replay_history` | Folding observations preserves the exact event sequence in newest-first form |
| `native_trace_safe` | Every context on a LeanLTL trace satisfies the per-decision implication |
| `cancellation_correct` | The executable airline cancellation predicate matches its stated eligibility proposition |
| `external_cannot_override` | Optional external approval cannot override a native denial |

`Audit.lean` lists exported safety theorems for `#print axioms`. Only Lean's standard
`propext`, `Classical.choice`, and `Quot.sound` are accepted by the verification script.
No `sorry` or custom axiom is needed in the implementation.

The generic authorization theorem is conditional on the predicates' meanings. Except
for the separate cancellation statement, it does not independently prove that every
domain predicate faithfully captures its English source. Predicate tests and the
coverage registry supplement, but do not replace, that obligation.

`native_trace_safe` quantifies over contexts carrying their own histories. It is not
a theorem that arbitrary supplied histories are authentic or consistent with prior
contexts, nor a proved state-machine refinement of Python execution. Finite-prefix
admission can enforce safety; it cannot guarantee eventual task completion, truthful
free-form messages, refunds arriving days later, or a user eventually responding.

## Enforcement protocol

```text
original tool proposal
  → lock host and authoritative backend
  → snapshot current facts and validate approval binding
  → Lean admission and dispatch reservation
  → commit command and decision to SQLite
  → execute the original tool call
  → record success or unknown outcome before returning
```

No tool runs on a native denial, schema/adapter error, timeout, or failed admission
journal write. The engine's version is checked on every command. Requests and outcomes
are correlated by IDs, event identity, normalized inputs, and amount; duplicate
requests/outcomes are rejected. The existing `confirmed` guard consumes confirmation
at dispatch, not on successful completion. The Dogwood article packs instead use
reusable response approvals to preserve the article's semantics.

The journal is single-writer, uses SQLite WAL with `synchronous=FULL`, and pins the
principal, domain, and compiled engine hash. A restart replays monitor commands and
compares every decision without executing tools. Failure after a durable reservation
but before a durable outcome leaves an unresolved dispatch; retries remain blocked.
The implementation does not claim exactly-once effects or automatically reconcile
unknown outcomes. That needs a backend idempotency/reconciliation protocol.

The `dogwood.*` example packs are individually selectable demonstrations, not additional
rules automatically applied to the benchmark packs. Unlike those packs, they do not
include the single-flight guard: the native monitor can admit multiple calls before
outcomes arrive and enforce the request-based budget. The Python host still serializes
its execution path. The deliberately unsafe response-only example is available only
to `leanguard-conformance`, a read-only executable with no tool dispatch capability.

The offline runner accepts trace fragments starting with responses because the article
omits their earlier requests. This does not bypass live `validateOutcome`: unmatched
or altered outcomes remain errors in the live engine. Article fixtures and replay
results are tests, not a proof of equivalence between Lean and every Dogwood policy.

## Trusted computing base

- The host's code and operating environment, including its identity assignment,
  nondecreasing clock, canonicalization, process transport, and journal management.
  Assistant/user requestor roles must come from the trusted orchestrator, not model output.
- The adapter's faithful extraction of authoritative facts and exact units, and a lock
  or equivalent transaction mechanism respected by **all** environment writers.
- A genuine user-facing confirmation channel that faithfully presents the proposal.
  Trusted intent labels, such as insurance reasons, are assumptions about user input,
  not verified facts about the world.
- Complete interception: the agent must have neither backend credentials nor a second
  unguarded tool endpoint, local journal access, or the native engine's control channel.
  A Python object proxy is not an operating-system sandbox.
- The pinned compiled policy, Lean compiler/runtime, Python and dependencies, SQLite,
  and filesystem durability/access controls. Journals contain sensitive raw facts,
  proposals, and outcomes and need a private directory and an explicit retention policy.

Separate journals for the same principal/resource do not share quotas or one-shot
history. Production deployments need one authoritative coordination domain, not a
new empty journal per conversation. A changed backend must not be paired silently
with an old journal; backend recovery is the integrator's responsibility.

OPA is not integrated. The proved Boolean conjunction is a future composition rule,
not a proof of OPA, an HTTP adapter, or Rego policy equivalence. Any future adapter must
fail closed on undefined/missing/error results, bind to the same state revision, and
only restrict native authorization.
