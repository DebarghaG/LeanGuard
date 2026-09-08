# LeanLTL integration

LeanGuard's temporal language has a compositional interpretation in the pinned
LeanLTL dependency. `Formula.toLeanLTL` uses the completed `TraceSet` library directly;
it does not call LeanGuard's evaluator or its older `Holds` specification.
The sibling vendored checkout and Lake's dependency both identify revision
`7514f6f035e4b8944299f02ac80ba7145a2a1f29`. The Lake pin remains portable to standalone
checkouts; no sibling-directory dependency or modifications to LeanLTL are required.

## Representation and boundaries

`historyTrace [e₂, e₁]` is the finite LeanLTL trace with states
`[[e₂, e₁], [e₁], []]`. Advancing this trace walks toward the past. A state carries
the full remaining history because native atoms may inspect multiple events,
aggregates, or the length of that history. This preserves arbitrary atom meanings,
including their behavior on the empty history.

LeanLTL traces are nonempty, so the final empty-history state makes the embedding
total. `historyTrace_shift` proves that shifting by `i` gives exactly the trace of
`h.drop i`, including the terminal state. Window predicates exclude empty histories,
so that state never becomes a temporal witness. In particular, strong `previous`
is false on both an empty history and a singleton, even when its operand is a
negation that would be true on empty input. `once` and `since` are false on empty
input; ordinary atoms and Boolean connectives retain their original meanings there.

| Native constructor | LeanLTL interpretation |
|---|---|
| `atom`, `top`, `bot` | `TraceSet.of`, `true`, `false` |
| `neg`, `conj`, `disj` | `TraceSet.not`, `and`, `or` |
| `previous w p` | Strong next of the window predicate conjoined with `p` |
| `once w p` | Finally of the window predicate conjoined with `p` |
| `since w p q` | `p` until the window predicate conjoined with `q` |
| `within scope p` | Satisfaction of `p` on the re-embedded projected history |

Each temporal operator freezes its own current history as the metric origin before
shifting. `InPastWindow` independently specifies non-future timestamps and inclusive
age bounds; `inWindow_correct` proves the executable window test equivalent to it.
No timestamp-order assumption is needed by the correspondence theorem. Even `none`
rejects future witnesses. `since` checks its left operand strictly before the witness
in this reverse-time trace, including intervening positions outside a witness's
timestamp window if the supplied history is unordered.

Projection is explicit and re-anchors at the current head. Nested projections and
windows therefore preserve the native semantics. These metric and scope operations
extend LeanLTL's trace sets; they are not claimed to be ordinary propositional LTLf
over individual events. LeanLTL's unfinished `LTLfMT` module is not imported.

## Theorems and policy authoring

`evaluate_leanLTL_correct` establishes, for every formula, atom interpretation, and
history:

```lean
evaluate atom p h = true ↔ (historyTrace h ⊨ p.toLeanLTL atom)
```

This is soundness and completeness over all histories. Adding a native formula
constructor requires extending both the exhaustive translation and its induction
proof before the default build can succeed. The existing
indexed `Holds` specification remains available and is connected by
`holds_iff_leanLTL`. `evaluate_eq_decide_leanLTL` identifies the native evaluator with
a constructive decision procedure for embedded LeanLTL formulas. The runtime keeps
its executable Boolean evaluator; LeanLTL supplies the independently connected
semantics and proof library.

Policy authors can state concrete checks directly in LeanLTL and prove them with
ordinary kernel reduction:

```lean
import LeanGuardProofs
open LeanGuard

example (atom : String → History → Bool) :
    ¬ (historyTrace [] ⊨ (Formula.previous none .top).toLeanLTL atom) := by
  exact (evaluate_leanLTL_correct atom _ []).not.mp (by simp [evaluate, inWindow])

example (atom : String → History → Bool) (p q : Formula String) (h : History) :
    evaluate atom (.once (some 60) (.disj p q)) h =
      evaluate atom (.disj (.once (some 60) p) (.once (some 60) q)) h :=
  evaluate_once_disj atom _ p q h
```

`evaluate_once_disj` is obtained from LeanLTL's `finally_or_distrib` theorem and
transported back to execution. `evaluate_of_leanLTL_imp` and
`evaluate_eq_of_leanLTL_eq` support further implication and rewrite proofs.
The theorem fixtures in `LeanGuard/TemporalTests.lean` use the verified decidability
instance with `by decide`, including expiry, nested clocks, scoping, and revocation.

`authorizationLeanLTL` expresses permit existence, every mandatory requirement, and
the absence of applicable forbids with LeanLTL connectives and quantifiers.
`authorize_leanLTL_correct` proves exact correspondence to native authorization.
`PolicyPack.toLeanLTL` adds the error gate, and `decision_leanLTL_correct` proves an
equivalence for the actual runtime allow bit. Exported theorems provide applicable
requirement/forbid guarantees and a permit witness.

`native_trace_leanLTL_safe` states this complete policy guarantee globally over
finite or infinite traces of decision contexts. `replay_leanLTL_correct` connects
the executable monitor fold to evaluation on the reversed observation sequence.
Confirmation proofs expose prior LeanLTL witnesses, non-consumption, and metric
expiry. `query_leanLTL_membership` proves that window-query membership is exactly
eventual satisfaction of its event, action, basis, scope, and time predicate.
Counts and sums remain native arithmetic over the selected history, preserving
multiplicity; they are not presented as temporal operators supplied by LeanLTL.

## Build and trust boundary

`Temporal.lean` contains semantic definitions and imports LeanLTL's `TraceSet.Defs`.
`TemporalProofs.lean`, `PolicyProofs.lean`, and `QueryProofs.lean` use the larger
LeanLTL proof library. This keeps the full mathlib proof-library imports out of
the executable's dependency path while checking all correspondence proofs in the
default build.

`lake build` includes `LeanGuardAudit`, which checks transitive axiom dependencies
of every public `LeanGuard` declaration in the imported library and theorem fixtures.
Only `propext`, `Classical.choice`, and `Quot.sound` are allowed. A `sorryAx`,
a compiler-trusting axiom generated by `native_decide`, or a custom axiom fails
the build.
`Audit.lean` also prints the dependencies of the named safety theorems, and
`scripts/verify.py` checks that every requested report is present.

These theorems cover the formal, finite-history policy evaluator and its Lean
decision functions. They do not establish the fidelity of every English policy,
Python execution, timestamp authenticity, or the external host's event stream.
The infinite-context theorem is a global safety implication, not a decision
procedure for arbitrary infinite-trace properties or a liveness guarantee. See
[the guarantee boundary](guarantees.md).

The [integration validation report](leanltl-validation.md) records the proof audit,
tests, and real Qwen3.5-4B τ² smoke run, including the model-run failures.
