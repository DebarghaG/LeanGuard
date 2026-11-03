# LeanLTL integration

LeanGuard's temporal operators are only useful if they mean what their names say.
To pin that down, every native formula is translated into
[LeanLTL](https://doi.org/10.4230/LIPIcs.ITP.2025.37), a Lean library for linear
temporal logics by Eric Vin, Kyle A. Miller and Daniel J. Fremont (ITP 2025), and
the executable evaluator is proved to agree with that translation on every
history. Policy authors get the payoff: you can prove properties of a policy
using LeanLTL's theorems and carry the results over to the runtime verdict.

The paper's supplementary software is the upstream
[`vITP25` release](https://github.com/UCSCFormalMethods/LeanLTL/releases/tag/vITP25).
LeanGuard depends on a fork pinned at revision
`7514f6f035e4b8944299f02ac80ba7145a2a1f29` in
[lake-manifest.json](../lake-manifest.json); a standalone checkout fetches it
without any sibling directory or local changes to LeanLTL. `Formula.toLeanLTL`
builds directly on LeanLTL's `TraceSet` library and never calls LeanGuard's own
evaluator or its indexed `Holds` specification, so the correspondence proofs
compare two independent definitions.

## How histories become traces

LeanGuard histories are newest first, so time in the embedded trace runs toward
the past. `historyTrace [e₂, e₁]` is the finite trace with states
`[[e₂, e₁], [e₁], []]`: each state is the whole remaining history, because native
atoms may look at several events, compute aggregates, or check the history's
length. Keeping the full suffix lets an atom mean exactly what it meant natively,
including on the empty history.

LeanLTL traces cannot be empty, and the final empty-history state is what makes
the embedding total. `historyTrace_shift` proves that shifting the trace by `i`
gives exactly the trace of `h.drop i`, terminal state included. Window predicates
exclude the empty history, so that terminal state can never serve as a temporal
witness. Concretely, strong `previous` is false on both an empty history and a
singleton, even when its operand is a negation that would be true on empty input.
`once` and `since` are false on empty input, while ordinary atoms and Boolean
connectives keep their usual meaning there.

| Native constructor | LeanLTL interpretation |
|---|---|
| `atom`, `top`, `bot` | `TraceSet.of`, `true`, `false` |
| `neg`, `conj`, `disj` | `TraceSet.not`, `and`, `or` |
| `previous w p` | Strong next of the window predicate conjoined with `p` |
| `once w p` | Finally of the window predicate conjoined with `p` |
| `since w p q` | `p` until the window predicate conjoined with `q` |
| `within scope p` | Satisfaction of `p` on the re-embedded projected history |

Each temporal operator records its current history as the origin for its window
before shifting. `InPastWindow` specifies windows independently (no future
timestamps, inclusive age bounds), and `inWindow_correct` proves the executable
window test equivalent to it. The correspondence theorem makes no assumption about
timestamp order, and even an unbounded `none` window rejects future witnesses.
Because the trace runs backwards, `since` checks its left operand at every position
strictly before the witness. If a supplied history is out of order, that includes
positions whose timestamps fall outside the witness's window.

Projection is explicit and re-anchors at the current head, which is why nested
projections and windows keep their native meaning. The metric and scope operators
extend LeanLTL's trace sets, so the language as a whole is richer than ordinary
propositional LTLf over individual events. LeanLTL's unfinished `LTLfMT` module is
not imported.

## Theorems for policy authors

The central result is `evaluate_leanLTL_correct`, which holds for every formula,
atom interpretation and history:

```lean
evaluate atom p h = true ↔ (historyTrace h ⊨ p.toLeanLTL atom)
```

This is soundness and completeness at once. Adding a native formula constructor
means extending both the exhaustive translation and this induction proof, or the
default build fails. `holds_iff_leanLTL` connects the indexed `Holds`
specification to the same semantics, and `evaluate_eq_decide_leanLTL` shows the
native evaluator is a constructive decision procedure for embedded LeanLTL
formulas. The runtime still runs its own Boolean evaluator; LeanLTL provides the
semantics and the proof library it is checked against.

You can state concrete checks in LeanLTL and prove them by ordinary kernel
reduction:

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

The second example shows the pattern for reusing LeanLTL: `evaluate_once_disj`
comes from LeanLTL's `finally_or_distrib` and is transported back to execution.
`evaluate_of_leanLTL_imp` and `evaluate_eq_of_leanLTL_eq` do the same for your own
implications and rewrites. The fixtures in `LeanGuard/TemporalTests.lean` use the
verified decidability instance with `by decide` to cover expiry, nested clocks,
scoping and revocation.

The same approach extends from single formulas to whole policies.
`authorizationLeanLTL` expresses "some permit holds, every applicable requirement
holds, and no applicable forbid holds" with LeanLTL connectives and quantifiers,
and `authorize_leanLTL_correct` proves it matches native authorization exactly.
`PolicyPack.toLeanLTL` adds the error gate, and `decision_leanLTL_correct` proves
equivalence with the allow bit the runtime actually returns. From there, exported
theorems give you a permit witness and the requirement and forbid guarantees for
any admitted call.

Several theorems connect these results to the runtime and to the guards:

- `native_trace_leanLTL_safe` states the complete policy guarantee globally, over
  finite or infinite traces of decision contexts. It is a safety implication; it
  does not decide arbitrary infinite-trace properties or promise liveness.
- `replay_leanLTL_correct` relates the executable monitor fold to evaluation on the
  reversed sequence of observations.
- The confirmation theorems expose a prior LeanLTL witness, non-consumption, and
  the metric expiry window.
- `query_leanLTL_membership` proves that window-query membership is exactly
  eventual satisfaction of the query's event, action, basis, scope and time
  predicate. Counts and sums over the selected events stay native arithmetic that
  preserves multiplicity, and are not LeanLTL operators.

## Build layout and axiom audit

`Temporal.lean` holds the semantic definitions and imports only LeanLTL's
`TraceSet.Defs`. The heavier proof library is used by `TemporalProofs.lean`,
`PolicyProofs.lean` and `QueryProofs.lean`. That split keeps mathlib's proof
imports out of the executable's dependency path while every correspondence proof
is still checked in the default build.

`lake build` also builds `LeanGuardAudit`, which follows the axiom dependencies of
every public `LeanGuard` declaration in the library and theorem fixtures. Only
`propext`, `Classical.choice` and `Quot.sound` are allowed, so a `sorryAx`, the
compiler-trusting axiom that `native_decide` introduces, or a custom axiom fails
the build. `Audit.lean` prints the dependencies of the named safety theorems, and
`scripts/verify.py` checks that every requested report is present.

All of this concerns the formal evaluator over finite histories and the Lean
decision functions. Whether an English policy, the Python host, timestamps or the
host's event stream are faithful is outside these proofs; the
[guarantee boundary](guarantees.md) spells out what is assumed.
