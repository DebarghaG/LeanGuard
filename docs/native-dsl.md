# Authoring native policies

A LeanGuard policy is a Lean module. You write rules as ordinary Lean declarations,
compile them into an executable, and the Python host consults that executable
before every tool call. There is no policy parser and no translation from Cedar or
Rego, and nothing the agent sends at run time is ever executed as policy code.
JSON appears only as the wire format between the host and the engine.

## What happens at run time

When the agent calls a tool, it produces a tool name and JSON arguments that match
a schema you compiled in. The host takes a snapshot of the authoritative facts the
policy needs (account balances, order status, and so on), attaches the principal
(the user or account the call acts for), the session, a timestamp and, if the call
carries an approval, its binding, then sends the result to the engine as an
`admit` message. A binding is a digest of the exact proposal the user approved,
so a "yes" to one call cannot be replayed against a different one.

Inside the engine, `Runtime.eventFromJson` and the data accessors decode that
message, and `Runtime.handle` builds a Lean `Context` and calls `decidePolicy`
against the history recorded so far. Admission is the engine's yes-or-no answer;
if it says yes, it also reserves a dispatch, meaning the call is recorded as in
flight. The host writes that decision to its journal, a durable SQLite log, and
only then runs the tool. No language model and no proof search sit on this path.

Two harder problems sit outside it. Turning an English policy document into Lean
rules is an offline authoring task. Working out whether "yes, that one" in a
conversation approves a particular set of arguments is a consent problem: a
trusted user interface has to bind the approval, or whatever component interprets
the conversation has to be treated as an unverified assumption.

## Events and checks

`Event` records the principal, conversation, action, resource, binding, timestamp
and kind. Histories are newest first and include the current request. The kinds
cover requests, reserved dispatches, outcomes (success, failure or unknown) and
trusted observations from the user. Only `admit` can produce a dispatch.

Events also carry `inputJson`, `outputJson` and `factsJson`. These are strings of
serialized JSON rather than parsed trees, which keeps structural equality on
events decidable. `EventField α` decodes a nested path from them into a typed Lean
value and reports decoding failures as explicit errors.

Where each field comes from matters for what a policy can trust:

- Inputs are the normalized arguments of the actual request. Any output claimed
  inside a request is discarded, and an outcome's input and amount are checked
  against its dispatch.
- `factsJson` is the authoritative snapshot taken at admission. A validated outcome
  inherits it from its dispatch, so an outcome payload cannot overwrite those facts.
- Outputs are the tool's actual results, supplied by the host.

Inputs and facts use the adapter's normalized units. Outputs keep the tool's own
units unless the adapter normalizes them too, so a query over historical data has
to pick a field and stick with its unit convention.

A `Check` is a named, pure Lean predicate, `Context → Except String Bool`. It can
read the current arguments, the authoritative facts, and the history handed to it
by the temporal evaluator. Inside a check, `request` is always the original
request being decided, while `history.head?` is whichever event the evaluator is
currently looking at. Use `eventCheck` for predicates that relate an event to the
request, and the `Data` accessors to decode JSON so that a missing or ill-typed
field fails closed.

## Rules and decisions

A `Rule` has a stable ID, a list of actions, an effect, a condition and a source
reference. An action is allowed exactly when at least one matching `permit` holds,
every matching `require` holds, no matching `forbid` holds, and no applicable
predicate reported an error. A broad permit therefore cannot bypass a `require`.

Errors are never silently absorbed: an error under a negation does not become
`true`, and an error in one branch of a disjunction is not hidden because another
branch succeeded. Error collection does respect time, though. `previous` checks its
operand only if the previous position exists and lies in the window, `once` checks
every candidate in the window, and `since` also checks the left operand at every
position between the witness and now. Expired or future positions contribute no
errors. `evaluationErrors_eq_nil_iff` proves this behaviour against the separate
`ErrorFree` specification.

## Temporal operators

| Lean constructor | Meaning at the current evaluation position |
|---|---|
| `.previous window p` | The previous event exists, is in the window, and satisfies `p` |
| `.once window p` | Some position, including the current one, satisfies `p` in the window |
| `.since window p q` | A past or current `q` witness exists, and `p` holds at every later position |
| `.within scope p` | Evaluate `p` on the history projected to the current head's scope key |
| `p ⋏ q`, `p ⋎ q`, `.neg p` | Boolean conjunction, disjunction, and negation |

Windows are integer seconds. `some 3600` is an inclusive one-hour bound, so an
event exactly an hour old counts, and `none` means unbounded. Events with future
timestamps never count as past witnesses. Each operator measures its window from
the position where it is evaluated, so nesting `previous` inside `once` moves the
reference point. For "a successful read within an hour of this request", use
`.once (some 3600)` around a `success` event predicate, as `Examples.recentlyRead`
does.

A scope restricts the history to related events: the same principal, the same
conversation `(principal, session)`, or the same resource `(principal, resource)`.
Project with `.within` before using `previous` or `since`. If you instead compare
IDs inside an atom, unrelated events interleaved in the history still shift what
"previous" points at. Scopes are chosen per rule rather than applied globally, so
a resource-scoped rule can deliberately span conversations.

Every constructor has a compositional LeanLTL meaning through `Formula.toLeanLTL`.
Import `LeanGuardProofs` for `evaluate_leanLTL_correct`, the verified decidability
instance, and the admission, confirmation, query and replay theorems. You can
state a policy property directly as LeanLTL satisfaction or implication and carry
it over to the executable verdict; [the LeanLTL guide](leanltl.md) shows how.

## Reusable guards

`confirmed` requires an earlier confirmation that matches the request's principal,
conversation, acting agent, action, resource and binding, with no later revocation
and no earlier dispatch using the same binding. That last condition makes each
approval single-use. The host computes the binding from the original arguments,
the state revision (a token that changes whenever relevant backend state changes),
the policy binary's fingerprint and the proposal shown to the user. An agent
saying "the user agreed", or a tool response, cannot create a confirmation event.

`confirmedWithin seconds` adds an inclusive expiry, measured from the decision's
clock, on top of the same single-use and revocation conditions. Plain `confirmed`
has no expiry. The [article examples](../LeanGuard/DogwoodExamples.lean) take a
different approach on purpose: they use a reusable `ApproveSale` response
predicate that stays valid for an hour.

`observed actions` requires a successful tool event for one of `actions` on the
same resource, in the same conversation and workflow. It shows that a read
happened at some point. Whether the data is still current is a separate question,
which is why eligibility checks read the authoritative snapshot taken at admission.

`neverDispatched actions` enforces one-shot actions per resource, across sessions.
`singleFlight` blocks a call while an earlier dispatch in the same conversation or
on the same resource has no recorded outcome. An unknown outcome never releases
that reservation on its own.

`quota count amount seconds` counts the principal's dispatches in an inclusive
window, across all action names, and adds the proposed request's amount before
allowing the reservation. Counts and money are exact Lean integers with no
floating point, and repeated events count each time. To limit only certain
actions, write a custom quota with your own predicate.

## Historical queries

Some rules depend on aggregates over past calls: how many distinct recipients
this user has paid in the last hour, or whether a transfer is larger than
everything before it.

```lean
import LeanGuard.Query
open LeanGuard

def transfers : WindowQuery := ⟨"Transfer", .requests, 3600, .principal⟩

def recipientLimit : Formula Check := check "recipients" fun c ↦ do
  return (← transfers.countDistinct (inputString "user") c) ≤ 3

def antiSpike : Formula Check := check "anti_spike" fun c ↦ do
  let prior ← ({ transfers with basis := .successes }).sum (inputNat "amount") c
  return (← Data.nat c.arguments "amount") ≤ prior
```

A query picks an action, a basis, a scope and an inclusive time window. The basis
decides which events count: `.requests` is every recorded request including
denials and the current candidate, `.dispatches` is admitted calls, and
`.successes` is completed successful outcomes. Queries keep every matching event,
even several with the same timestamp. `countDistinct` removes duplicate values,
so two transfers to the same user count once. `inputField` and `outputField` take
a nested path and an explicitly typed decoder.

Queries only see events that are already in the history. For a budget that must
include the call being decided, use `quota`, which counts the proposed dispatch.
Counting completed outcomes alone cannot limit effects that are still in flight;
the [conformance runner](../scripts/conformance.py) includes an executable negative
control showing that failure.

## Add a pack

1. Write a module that imports `LeanGuard.Policy` and declares named rules with
   source references. Policy code must be total and must not add untrusted axioms.
2. Declare a native `Schema` for each tool and wrap the pack with `withSchemas`.
   Tools without a schema stay denied by default. Schemas support primitives,
   enums, arrays, records with required and optional fields, and alternatives,
   and validation stops at depth 64.
3. In your own Lake project, import `LeanGuard.Server` and define
   `main := LeanGuard.serve pack`, or use `serveVerified` to attach the proof
   contract described below. The [complete example](../examples/custom_policy/lakefile.toml)
   uses a local path dependency; for independent use, replace `path` with `git`
   and an immutable `rev`. Journals reject a changed binary fingerprint, so
   switching binaries needs a deliberate journal migration.
4. Write a trusted adapter. The tool receives the original arguments, while Lean
   receives normalized arguments and facts. The adapter's lock must cover every
   writer to the backend, including user-side tools.
5. Test allowed and denied traces, wrong principals and resources, stale
   approvals, malformed facts, timestamps on the window boundary, errors, retries,
   and the actual effects on the backend.

Contexts are JSON-backed today, so checks look fields up by name. A typed record
decoder would remove those repeated lookups and let you prove domain invariants,
and the evaluator correctness theorem would carry over unchanged.

## Proof contracts and downstream audits

`VerifiedPolicy` pairs a pack with the property it is meant to enforce. It holds
`pack`, a descriptive `property` label, `Safe : Context → Prop`, and
`sound : ∀ ctx, (decidePolicy pack ctx).allow = true → Safe ctx`. The proof has to
be about the exact pack being served. Lean will happily accept a vacuous
`Safe`, or a pack that denies everything, so the property itself still needs a
human reviewer.

The [document policy](../examples/custom_policy/Guard.lean) proves approval
evidence, non-consumption and dispatch-reservation bounds. Its default
[audit target](../examples/custom_policy/GuardAudit.lean) imports the executable
and audits the pack, the theorem and the entry point, plus every declaration in the
downstream and LeanGuard namespaces. `LeanGuard.Audit.check roots namespaces`
follows dependencies transitively, even outside those namespaces. It rejects
missing roots, empty namespaces, `sorryAx`, and every axiom other than `propext`,
`Classical.choice` and `Quot.sound`.

Run the example from its own directory after installing the Python host:

```sh
cd examples/custom_policy
lake update
lake build
../../.venv/bin/python run.py
```

Keep the audit among the package's default build targets. Use `serve` for
exploratory packs and `serveVerified` when you want the proof contract linked in;
neither does any proof search at run time. If you publish binaries, ship the
audited sources, build provenance and proof audit results with them. The native
manifest reports the protocol version, rule IDs, schemas, the schema depth limit
and property labels, and the Python engine adds the executable's SHA-256.

## Recorded trace API

Use these functions to ask what a policy would have decided on a recorded trace,
for example a saved journal or an imported dataset. Both call the engine's native
`audit` operation, which leaves the live history and version untouched and never
runs a tool.

`audit(engine, request, history)` takes the prior events in chronological order
and the request separately. `replay(engine, events)` walks a whole trace and yields
one `AuditResult` per request while keeping every recorded event in the history.

Each `TraceEvent` has `id`, an integer-second `time`, `kind`, `principal`,
`session`, `action`, `resource`, `binding` and a nonnegative integer `amount`.
Requests also carry `input` (the normalized arguments) and `facts` (the admission
snapshot); outcomes may carry `output`. Historical inputs and facts must use the
units the policy expects. `GuardHost.events()` exports exactly this shape,
including recorded dispatches. Events with equal timestamps keep their list order.
The importer has to resolve dataset-specific aliases and pair responses with
requests itself, because the API will not guess.

The native `decision` is only as good as the evidence supplied, which is why each
result also has an `assessment`: `allowed`, `denied` or `insufficient_evidence`.
The last appears when decoding fails, when a request lacks inputs or facts, when
`history_complete=False`, or when the record lists `missing_evidence` labels.
Those labels stay attached for the rest of the replay. They describe how complete
the evidence is; they do not classify model misconduct or policy overrefusal, and
the importer must flag any gaps that the trace itself cannot reveal.

Replay never invents confirmations, dispatches or outcomes. Recorded outcomes
still advance the history after a denied call, so later results describe the
original run rather than what would have happened under enforcement. Journals
contain private facts and consent records, so control access to anything you
export.
