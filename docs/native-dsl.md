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
Events also retain `inputJson` and `outputJson`: native strings containing serialized
JSON, preserving decidable structural event equality. `EventField α` decodes nested
paths into typed Lean values with explicit errors; these strings are data, never code.
Admission supplies historical inputs from the actual normalized arguments, discards
any claimed request output, and validates outcome input/amount against its dispatch.
The host supplies actual tool results as output. Inputs use the adapter's normalized
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
remains unbounded for existing packs. The article examples deliberately use a separate,
reusable `ApproveSale` response predicate with a one-hour lifetime.

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
negative control in the conformance runner.

## Add a pack

1. Define a module importing `LeanGuard.Policy` and declare named rules with source
   references. Policy code must be total and must not introduce untrusted axioms.
2. Add native `Schema` declarations and wrap the pack with `withSchemas`. Unknown
   tools remain default-denied. The schema subset supports primitives, enums, arrays,
   records with required/optional fields, and alternatives; validation has depth 64.
3. Register the pack in `Runtime.packFor`, then rebuild the executable. A new binary
   needs a deliberate journal migration; existing journals reject fingerprint changes.
4. Supply a trusted adapter: original arguments go to the tool, normalized arguments
   and facts go to Lean. Its lock must cover every backend writer, including user tools.
5. Test allowed and denied traces, wrong principals/resources, stale approvals,
   malformed facts, boundary timestamps, errors, retries, and actual backend effects.

The current JSON-backed contexts are an intentional boundary, not fully typed domain
records. A future native record decoder can remove repeated field lookups and prove
domain invariants; the existing evaluator correctness theorem remains reusable.
