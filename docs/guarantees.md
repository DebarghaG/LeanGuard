# What LeanGuard guarantees

LeanGuard's claims come in three layers, and it helps to keep them apart. Some
things are proved in Lean and checked by the kernel. Some are enforced by the
Python host at runtime, by code that is tested but not proved. And some are
assumptions about your deployment that nothing in this repository can check.
This page goes through each in turn.

## Proved in Lean

These theorems are about the functions the runtime actually executes.

| Statement | What it establishes |
|---|---|
| `evaluate_correct` | Boolean temporal evaluation equals the separate `Holds` semantics |
| `historyTrace_shift`, `inWindow_correct` | History suffixes match LeanLTL shifts; executable windows match independent metric predicates |
| `holds_iff_leanLTL`, `evaluate_leanLTL_correct` | Every formula, including nested windows and scopes, agrees with its compositional LeanLTL interpretation |
| `evaluate_eq_decide_leanLTL` | Native evaluation is a constructive decision procedure for the embedded LeanLTL formulas |
| `authorize_leanLTL_correct`, `decision_leanLTL_correct` | Authorization and the actual admission decision equal their complete LeanLTL policy semantics |
| `authorized_permit_leanLTL`, `decision_requirement_leanLTL`, `decision_no_forbid_leanLTL` | Admission has a permit witness and satisfies every applicable requirement and no forbid, in LeanLTL |
| `evaluate_of_leanLTL_imp`, `evaluate_eq_of_leanLTL_eq`, `evaluate_once_disj` | LeanLTL implications and rewrites transfer to executable policy evaluation |
| `project_membership`, `project_idempotent` | Explicit scope projection selects exactly matching keys and is stable |
| `authorized_requirement`, `authorized_no_forbid` | Allow cannot bypass a mandatory rule or an applicable true forbid |
| `decision_sound`, `decision_no_errors` | The actual decision's allow bit implies native authorization and an empty error list |
| `evaluationErrors_eq_nil_iff` | Error collection equals the independent specification over applicable windows, scopes and Boolean branches |
| `confirmation_has_witness`, `confirmation_not_consumed` | The actual confirmation formula requires a prior matching witness and no matching prior dispatch |
| `confirmedWithin_preserves`, `confirmedWithin_recent_witness` | Adding expiry preserves the one-use guard and requires an in-window confirmation witness |
| `query_membership`, `query_window` | A query selects exactly its matching events, all within its inclusive non-future window |
| `query_leanLTL_membership` | Query membership equals eventual satisfaction of its scoped, timed LeanLTL event predicate |
| `confirmation_leanLTL_witness`, `confirmation_leanLTL_unconsumed`, `confirmedWithin_leanLTL_recent_witness` | Confirmation acceptance has prior LeanLTL evidence, no consumption, and the specified expiry window |
| `distinct_membership`, `distinct_duplicate` | Deduplication preserves value membership and a duplicate value does not change the result |
| `quota_reservation_bound` | Inserting the new dispatch after a successful quota check preserves its count and amount bounds |
| `reservation_retained`, `deny_no_reservation` | The reservation operation adds a dispatch only on allow |
| `replay_history` | Folding observations preserves the exact event sequence in newest-first form |
| `replay_leanLTL_correct` | Evaluation after the monitor fold agrees with LeanLTL on the reversed observations |
| `native_trace_safe` | Every context on a LeanLTL trace satisfies the per-decision implication |
| `native_trace_leanLTL_safe` | Every admitted context on a LeanLTL trace satisfies its complete translated policy, including the error gate |
| `cancellation_correct` | The executable airline cancellation predicate matches its stated eligibility proposition |
| `chronological_correct` | The itinerary timing check is equivalent to positive flight durations and arrival before every subsequent departure |
| `delayResolved_witness` | Historical delay eligibility requires a correlated successful change/cancellation with a qualifying pre-dispatch snapshot |
| `billRecorded_identity`, `recordedBills_witness` | A bill-list witness is an actual returned bill with matching bill/customer IDs |
| `external_cannot_override` | Optional external approval cannot override a native denial |

### How the proofs are checked

The default build includes `LeanGuardAudit`, which walks the transitive axiom
dependencies of every public LeanGuard declaration, the theorem regression files,
and the live runtime and offline replay entry points. The only axioms allowed are
Lean's standard `propext`, `Classical.choice` and `Quot.sound`, so a `sorry`, the
axiom that `native_decide` introduces, or any custom axiom fails the build. The
vendored LeanLTL module `LTLfMT` is unfinished, and LeanGuard doesn't import it.
`Audit.lean` also prints `#print axioms` reports for the exported safety theorems,
and `scripts/verify.py` fails if any report is missing.

Downstream packages run the same audit over their own code with
`LeanGuard.Audit.check`, giving it their declaration roots and namespaces. If you
use `serveVerified`, `VerifiedPolicy.sound` ties the executable pack you ship to
the safety property you stated. Whether that property says anything useful, and
whether your adapter feeds it honest data, are questions for review; the compiled
server doesn't recheck a proof on each request. The
[LeanLTL guide](leanltl.md) covers how traces are represented and how the
correspondence proofs work.

### Where the proofs stop

The authorization theorems hold whatever the domain predicates mean. They don't
show that a predicate like "this order is eligible for cancellation" matches the
English policy it was written from; the airline cancellation rule is the one
exception with its own correctness theorem. For the rest, predicate tests and the
[coverage notes](coverage.md) are evidence, not proof.

`native_trace_safe` is about contexts that carry their own histories. It doesn't
say those histories are genuine, that they agree with earlier contexts, or that
the Python host's behaviour refines the Lean model.

And admission checks can only enforce safety: something bad never happens. They
can't make something good happen eventually, so LeanGuard can't promise that a
task finishes, that the agent's free-text replies are true, that a refund arrives
days later, or that the user ever answers.

### Consent

Approval exists to constrain what the agent does. If a
customer approves buying a purple shirt for a stated price, that approval must not
let the agent buy a black shirt, or charge more. The host binds each approval to
the exact arguments and the backend revision, and the Lean guard requires a
matching approval that hasn't been used or revoked. The agent saying "the customer
approved" counts for nothing.

The weak point is whoever produces the approval. In the benchmark experiments a
second model plays the customer's approval screen, and that model is an
unverified consent authority. If it approves the black shirt by mistake, the
formula has no way to tell that from a real customer approving a new proposal,
and no amount of prompting fixes this. End-to-end consent needs approval that is
structured and independently authorized, plus enforcement that the call stays
within it. Turning free-form dialogue into that kind of approval is a separate
problem, and nothing here proves that a model understands what a user agreed to.

## Enforced by the host

Every call goes through the same sequence:

```text
original tool proposal
  → lock host and authoritative backend
  → snapshot current facts and validate approval binding
  → Lean admission and dispatch reservation
  → commit command and decision to SQLite
  → execute the original tool call
  → record success or unknown outcome before returning
```

The tool doesn't run if Lean denies the call, if the schema or adapter reports an
error, if the engine times out, or if writing the decision to the journal fails.
The host checks the engine's version on every command. Requests and outcomes are
matched by ID, event identity, normalized inputs and amount, and duplicates are
rejected.

When Lean admits a call it records the authoritative facts from the snapshot on
the request and on the dispatch. The matching outcome inherits those facts from
the dispatch, so a tool result can't overwrite them with claims of its own, and
journal replay rebuilds them from the original commands. The built-in `confirmed`
guard uses up an approval when the call is dispatched, whether or not it later
succeeds. The Dogwood article packs instead use reusable approval responses,
because that is what the article describes.

### The journal

Each journal has a single writer. It uses SQLite in WAL mode with
`synchronous=FULL`, and it is pinned to one principal, one domain and the hash of
one compiled engine. On restart the host replays the recorded commands and checks
that every decision comes out the same, without running any tools. If replay
fails, the engine channel stays closed until a full replay succeeds. On shutdown
the host waits for the running tool to finish and its outcome to be recorded
before releasing the journal lock.

If the process dies after a dispatch is recorded but before its outcome is, that
dispatch stays unresolved and blocks retries. LeanGuard doesn't promise
exactly-once effects and doesn't reconcile unknown outcomes on its own; that
needs an idempotency or reconciliation protocol with your backend.

### The Dogwood example packs

The `dogwood.*` packs demonstrate the examples from the Dogwood article. You
select them explicitly; they are never added to the benchmark packs. They also
leave out the single-flight guard, so the Lean monitor can admit several calls
before their outcomes arrive and enforce a budget counted over requests. The
Python host still runs those calls one at a time. The one deliberately unsafe
example, which accepts responses alone, is compiled only into
`leanguard-conformance`, a read-only executable that can't dispatch tools.

The article shows trace fragments that begin with responses whose requests
aren't included, so the offline runner accepts that shape. The live engine
doesn't: `validateOutcome` still rejects an outcome that doesn't match a
dispatch. The article fixtures are tests, and agreeing with them doesn't make
LeanGuard equivalent to Dogwood in general.

## What you have to trust

- The host and its environment. That includes how it assigns identities, a
  clock that never goes backwards, argument canonicalization, the process
  transport and the journal. Whether a message came from the assistant or the
  user must be decided by your orchestrator, never by model output.
- The adapter. It must extract authoritative facts with exact units, and it
  must provide a lock or transaction that every writer to the backend respects.
- The approval screen. It must show the user the actual proposal. Labels the
  user supplies, such as the reason for an insurance claim, are taken as given;
  LeanGuard doesn't check them against the world.
- Complete interception. The agent must not hold backend credentials, a
  second unguarded way to reach the tools, access to the journal, or the engine's
  control channel. A Python proxy object is no substitute for an operating-system
  sandbox.
- The toolchain. The pinned compiled policy, the Lean compiler and runtime,
  Python and its dependencies, SQLite, and the filesystem's durability and access
  controls. Journals hold sensitive raw facts, proposals and outcomes, so keep
  them in a private directory and decide how long to retain them.

Quotas and one-time rules only work within a journal. Two journals for the same
principal and resource don't see each other's history, so a production
deployment needs one authoritative journal per coordination domain rather than a
fresh one per conversation. Likewise, don't pair a changed backend with an old
journal; restoring the backend after a failure is the integrator's job.

## Open Policy Agent

OPA isn't integrated. Lean proves that combining the native decision with an
external one by conjunction can only restrict what the native policy allows
(`external_cannot_override`), but there is no OPA adapter, HTTP client or Rego
equivalence proof. A future adapter would have to deny on undefined, missing or
error results, bind to the same backend revision, and only ever narrow the native
decision.
