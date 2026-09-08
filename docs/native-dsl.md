# Authoring native policies

Policies are compiled, trusted Lean modules. JSON is only the transport and domain
data boundary; it is not an alternative policy DSL. There is no runtime policy parser,
Cedar/Rego translation, dynamic compilation, or agent-authored predicate execution.

## Tool calls are data, not new Lean programs

At run time, the agent emits a schema-defined tool name and JSON arguments. The
Python host snapshots authoritative domain facts and adds the principal, session,
timestamp, and correlation binding. It sends an `admit` JSON message to the already
compiled Lean executable. `Runtime.eventFromJson` and the data accessors decode
that message; `Runtime.handle` constructs the Lean `Context` and calls
`decidePolicy` against the existing history. The host dispatches only after an
allow decision is durably recorded. No LLM translation or new proof search occurs
on that path.

Translating English policy documents into native Lean declarations is a separate,
offline authoring/autoformalization problem. Extracting intent from free-form user
conversation is a third problem: schema decoding does not establish that “yes,
that one” approves particular arguments. A trusted UI must bind that approval,
or the language-to-evidence component must be treated as an unverified assumption.

## Representation

`Event` separates principal, conversation, action, resource, correlation binding,
timestamp, and kind. Histories are newest-first and include the current request.
The runtime distinguishes requests, reserved dispatches, successful/failed/unknown
outcomes, and trusted user observations. Only `admit` makes a dispatch decision.
Events also retain `inputJson`, `outputJson` and `factsJson`: native strings containing serialized
JSON, preserving decidable structural event equality. `EventField α` decodes nested
paths into typed Lean values with explicit errors; these strings are data, never code.
Admission supplies historical inputs from the actual normalized arguments, discards
any claimed request output, and validates outcome input/amount against its dispatch.
`factsJson` records the authoritative admission snapshot. A validated outcome inherits
it from its dispatch; an outcome payload cannot replace those facts. The host supplies
actual tool results as output. Inputs and admission facts use the adapter's normalized
units; output payloads retain the tool's original units unless an adapter explicitly
normalizes them. A query must choose a field and unit convention consistently.

`Check.run : Context → Except String Bool` is a named pure Lean predicate. It can read
the current arguments, authoritative facts, and the history supplied by the temporal
evaluator. `request` always denotes the original decision request; `history.head?`
denotes the event position currently being evaluated. Use `eventCheck` for correlated
event predicates and `Data` accessors for fail-closed JSON decoding.

`Rule` has a stable ID, action list, effect, condition, and source reference. An action
is allowed exactly when at least one matching permit holds, all matching requirements
hold, no matching forbid holds, and no applicable predicate evaluation reports an
error. A broad permit cannot bypass a `require`. Errors are not converted into a
successful negation or hidden by an unrelated successful disjunct.
Temporal error collection follows each operator's window and scope. `previous`
checks its operand only when the previous position exists in the window; `once`
checks all in-window candidates; `since` also checks every intervening left operand
for those candidates. Expired or future candidate positions do not introduce errors.
`evaluationErrors_eq_nil_iff` proves this against the separate `ErrorFree` specification.

## Temporal operators

| Lean constructor | Meaning at the current evaluation position |
|---|---|
| `.previous window p` | The previous event exists, is in the window, and satisfies `p` |
| `.once window p` | Some position, including the current one, satisfies `p` in the window |
| `.since window p q` | A past/current `q` witness exists, and `p` holds at every later position |
| `.within scope p` | Evaluate `p` on the history projected to the current head's scope key |
| `p ⋏ q`, `p ⋎ q`, `.neg p` | Boolean conjunction, disjunction, and negation |

`some 3600` denotes an inclusive one-hour bound in integer seconds; `none` denotes
unbounded history. An event exactly on the boundary counts. Future timestamps do not
count as past witnesses. Windows are measured at the position at which their operator
is evaluated, so nesting `previous` and `once` changes the window's reference point.
Use `.once (some 3600)` with a `success` event predicate for “successful read within an
hour of this request,” as in `Examples.recentlyRead`.

Every constructor has a compositional LeanLTL interpretation via `Formula.toLeanLTL`.
Import `LeanGuardProofs` for `evaluate_leanLTL_correct`, the verified decidability
instance, and the admission, confirmation, query, and replay theorems. Policy
properties can be stated directly as LeanLTL satisfaction or implication and
transported to executable verdicts. See [the proof API](leanltl.md).

Scopes are principal, conversation `(principal, session)`, or resource
`(principal, resource)`. Project before `previous` or `since`: checking equal IDs only
inside an atom would let interleaved foreign events change their meanings. These are
explicit scopes, not an automatic universal pin on every possible user-defined rule.
Resource-scoped rules can intentionally span conversations.

## Reusable guards

`confirmed` requires a prior confirmation matching principal, conversation, action,
resource, and binding, with no subsequent revocation and no prior dispatch using that
binding. The host binds the approval to original arguments, state revision, policy
binary fingerprint, and displayed proposal. Neither an agent's “yes” nor an arbitrary
tool response creates a confirmation event.
`confirmedWithin seconds` adds an inclusive expiry measured from the decision's clock
while preserving the same single-use and revocation conditions. `confirmed` itself
remains unbounded for existing packs. The [article examples](../LeanGuard/DogwoodExamples.lean)
deliberately use a separate, reusable `ApproveSale` response predicate with a
one-hour lifetime.

`observed actions` requires a successful same-conversation, same-resource tool event.
It is evidence that a read occurred, not a proof that it is still fresh. Current
eligibility checks independently read the current authoritative state at admission.
`neverDispatched actions` implements per-resource one-shot restrictions across sessions.
`singleFlight` blocks unresolved dispatches in the same conversation or for the same
resource. Unknown outcomes never release those reservations automatically.

`quota count amount seconds` counts dispatches for the principal in an inclusive
window, including all action names. It includes the proposed request's amount before
allowing reservation. Money and counters use exact Lean integers, not floating-point
arithmetic; repeated events count with multiplicity. Custom quotas can narrow the
action set with a native predicate.

## Historical queries

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

`EventBasis.requests` includes every recorded native request, including denials and
the current candidate. `.dispatches` selects admitted calls; `.successes` selects
completed successful outcomes. Queries additionally select action, scope key, and an
inclusive time window. They preserve event multiplicity, even at equal timestamps.
`countDistinct` removes duplicate **values**, not events. `inputField` and `outputField`
accept nested field paths and an explicitly typed decoder.

Queries do not add hypothetical dispatches. Use the existing `quota` helper when the
desired rule is a dispatch budget including the proposed candidate. Counting only
completed outcomes is not safe for limiting in-flight effects. See the executable
negative control in the [conformance runner](../scripts/conformance.py).

## Add a pack

1. Define a module importing `LeanGuard.Policy` and declare named rules with source
   references. Policy code must be total and must not introduce untrusted axioms.
2. Add native `Schema` declarations and wrap the pack with `withSchemas`. Unknown
   tools remain default-denied. The schema subset supports primitives, enums, arrays,
   records with required/optional fields, and alternatives; validation has depth 64.
3. In your own Lake project, define `main := LeanGuard.serve pack`, importing
   `LeanGuard.Server`. `serveVerified` additionally accepts the proof contract below.
   The [complete example](../examples/custom_policy/lakefile.toml) uses a local
   dependency; replace `path` with `git` and an immutable `rev` for independent use.
   A new binary needs deliberate journal migration; journals reject fingerprint changes.
4. Supply a trusted adapter: original arguments go to the tool, normalized arguments
   and facts go to Lean. Its lock must cover every backend writer, including user tools.
5. Test allowed and denied traces, wrong principals/resources, stale approvals,
   malformed facts, boundary timestamps, errors, retries, and actual backend effects.

The current JSON-backed contexts are an intentional boundary, not fully typed domain
records. A future native record decoder can remove repeated field lookups and prove
domain invariants; the existing evaluator correctness theorem remains reusable.

## Proof contracts and downstream audits

`VerifiedPolicy` contains `pack`, a `property` label, `Safe : Context → Prop`, and
`sound : ∀ ctx, (decidePolicy pack ctx).allow = true → Safe ctx`. The label is
descriptive metadata, not a certificate. The proof must establish the chosen
property for the exact pack being served. Review that property and its assumptions;
a vacuous proposition or an all-denying pack can still satisfy this type.

The [document policy](../examples/custom_policy/Guard.lean) proves approval evidence,
non-consumption, and dispatch reservation bounds. Its default
[audit target](../examples/custom_policy/GuardAudit.lean) imports the executable and
audits the pack, theorem and entry point, plus all declarations in the downstream
and LeanGuard namespaces. `LeanGuard.Audit.check roots namespaces` rejects missing
roots, empty namespaces, `sorryAx`, and all axioms except `propext`, `Classical.choice`,
and `Quot.sound`, including dependencies outside the selected namespaces.

Run the example from its own directory after installing the Python host:

```sh
cd examples/custom_policy
lake update
lake build
../../.venv/bin/python run.py
```

Keep the audit among the downstream package's default build targets. `serve` remains
available for exploratory packs; `serveVerified` links an explicit proof contract.
Neither function performs proof search at runtime. Published binaries need the
matching audited sources and build provenance. The native manifest exposes protocol
version, rule IDs, schemas, schema depth limit and property labels; the Python engine
adds the executable SHA-256. Proof audit results travel with release artifacts.

## Recorded trace API

`audit(engine, request, history)` accepts **prior events in chronological order**;
the request is supplied separately. `replay(engine, events)` yields one `AuditResult`
per request while preserving every recorded event. Both use the native `audit`
operation without changing the engine's live history/version or dispatching tools.

Each `TraceEvent` supplies `id`, integer-second `time`, `kind`, `principal`, `session`,
`action`, `resource`, `binding`, and nonnegative integer `amount`. Requests additionally
supply `input` (normalized arguments) and `facts` (the admission snapshot). Outcomes
may carry `output`; historical input/fact units must follow the policy contract.
`GuardHost.events()` exports this shape, including recorded dispatches. Equal
timestamps preserve list order. Dataset-specific aliases and response pairing must
be resolved by the importer; the public API does not guess them.

The native `decision` is conditional on the supplied evidence. `assessment` is
`allowed`, `denied`, or `insufficient_evidence`; decoding errors, missing request
inputs/facts, `history_complete=False`, or explicit `missing_evidence` labels produce
the last category. A record may carry a list of `missing_evidence` labels, retained
conservatively through subsequent replay. This metadata reports evidence coverage;
it is not a proved classifier of model misconduct or policy overrefusal. An importer
must flag omissions that cannot be inferred from the trace itself.

No confirmations, dispatches, or outcomes are synthesized. Recorded outcomes still
advance history after a denied call, so later results describe the original history,
not execution after enforcement. Journals contain private facts and consent data;
apply access controls when exporting them.
