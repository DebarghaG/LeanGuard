# How the repair experiment uses grind

The [repair experiment](../examples/repair/README.md) needs to prove goals like
"amount 40 is at most 70 and the policy allows it." That mixes arithmetic over a
hypothesis with a concrete policy computation, and sometimes needs a policy author's
own lemmas as well. Lean's `grind` tactic already contains most of the machinery for
this: normalization, congruence closure, theorem instantiation, arithmetic and case
splitting, all producing real proofs. This note explains which parts of grind
`guard_solve` reuses, and where the edges of that reuse are.

The reading below follows Lean master at
[`3baf82028468b3529ca83b20393596ec86828df6`](https://github.com/leanprover/lean4/tree/3baf82028468b3529ca83b20393596ec86828df6)
(2026-09-23). LeanGuard itself builds against its pinned Lean 4.33.1
(`819816b2e0a3bf405af45ae5c7af2491d8f5bee6`) and imports grind from that toolchain
rather than vendoring code from master. Because these are internal Lean APIs, run
the repair regression suite after any toolchain upgrade.

## Where grind lives

grind's source is split across three directories, and reading only the first gives
a misleading picture.

[`Init/Grind`](https://github.com/leanprover/lean4/tree/3baf82028468b3529ca83b20393596ec86828df6/src/Init/Grind)
holds the logical foundation. `Norm.lean` supplies the normalization equalities;
`Lemmas.lean`, `Cases.lean` and the arithmetic modules supply the lemmas proofs are
built from; `Ring`, `Module`, `Ordered`, `Order` and `AC` state the algebraic laws
each solver relies on. Syntax and configuration are defined here too. These laws
are what justify a generated proof: grind reasons about an operator because it has
an instance of the right structure, never because it recognizes the operator's name.

The search engine itself is in
[`Lean/Meta/Tactic/Grind`](https://github.com/leanprover/lean4/tree/3baf82028468b3529ca83b20393596ec86828df6/src/Lean/Meta/Tactic/Grind),
and the tactic frontend in
[`Lean/Elab/Tactic/Grind`](https://github.com/leanprover/lean4/tree/3baf82028468b3529ca83b20393596ec86828df6/src/Lean/Elab/Tactic/Grind).
Theorem indexing, the equality graph, search control and proof reconstruction are
all in these two.

## One goal through the engine

1. Elaborate parameters. `Elab/Tactic/Grind/Main.lean::mkGrindParams` assembles a
   `Grind.Params` from the configuration, theorem extensions, explicit facts and
   lemmas, normalization context, simprocs, symbol priorities and optional anchors.
   `Param.lean` handles theorem directions, local proof terms, the equation theorems
   of definitions, extension names and exclusions. All of this can be reused from
   outside the `grind` tactic.

2. Protect the caller's proof state. `Meta/Tactic/Grind/Main.lean::withProtectedMCtx`
   runs on a fresh goal at a deeper metavariable depth, so definitional-equality
   checks can't quietly assign metavariables that belong to the caller. It resolves
   its own delayed assignments before returning a proof. On an exception it admits
   the temporary goal and rethrows, which means a caller that is trying things
   speculatively has to restore its own saved state when an attempt fails. And a
   successful call only closes the one goal it was given; any other obligations are
   still the caller's.

3. Normalize and internalize. `initCore` unfolds reducible definitions,
   beta-reduces and processes hypotheses, and `assertExtra` adds explicit facts and
   activates lemmas. `Simp.lean::preprocessImpl` runs grind's normalizer, then
   canonicalizes projections, nested proofs, universe levels and shared subterms,
   composing the rewrite proofs with `Eq.mp`. The normalizer's discharger deliberately
   ignores local assumptions, which keeps its cache valid across search branches. This
   is a different thing from calling `simp_all` over and over.

4. Maintain an equality graph that produces proofs. `Types.lean::ENode` and
   `GoalState` keep the equivalence classes, parent links, congruence tables,
   generations, pending facts, splitting state and each theory solver's state.
   `Internalize.lean` registers terms and the propagation they can trigger;
   `Core.lean` merges classes, reinserts the affected parents, and wakes propagators
   and solvers. Every merge records why two terms are equal. A proposition is known to
   be true or false when it is equal to `True` or `False`, so equating `True` with
   `False` closes the goal. Some congruence proofs are built lazily, with separate
   markers for ordinary and symmetric equality congruence.

5. Instantiate relevant lemmas. `Theorems.lean` indexes lemmas by the symbols in
   their patterns, so a lemma only wakes up once those symbols appear in the goal
   instead of being tried against every fact. `EMatchTheorem.lean` infers normalized
   patterns, and `EMatch.lean` matches them modulo the equalities known so far. It
   supports multipatterns, fills in typeclass arguments, and builds genuine
   applications of the original theorem. Deduplication and modification times avoid
   repeated work. Each new term gets a higher generation, and the `gen`, `genLocal`,
   `instances` and `ematch` limits each bound a different source of growth. A
   `grind_pattern` constraint can hold an instance back until a guard is known, or
   cap term depth, size or instance count.

6. Coordinate theory solvers. A `SolverExtension` supplies hooks for
   internalization, new equalities and disequalities, solver actions and model-based
   theory combination. `Solvers.mkActionCore` combines the solvers' actions and
   `Solvers.mkAction` drains their pending facts, so the arithmetic, order and AC
   solvers all exchange proved facts through the same graph. Cutsat's proof builder
   turns its derivation back into a Lean proof, tracking only the variables and
   polynomials that mattered. A solver's model alone never counts as a proof.

7. Schedule the search. `Finish.lean::Action.mkFinish` builds this loop:

   ```text
   intros; assertAll;
   repeat (theory solvers <|> instantiate <|> splitNext <|> mbtc)
   ```

   The `<|>` here is grind's own combinator rather than ordinary tactic backtracking.
   An `Action` has separate continuations for "not applicable" and "made progress",
   and the right-hand action runs only when the left one was not applicable. An
   action can also run the rest of the search on several branches and look at the
   proofs that come back. `Split.lean::splitCore` uses that for non-chronological
   backtracking: if a branch's contradiction never used the case assumption, it
   closes the goal before the split directly. The `splits` limit bounds branching,
   but not the normalization work inside each branch.

8. Report or replay. `Grind.Result` carries any stuck goal, issues, counters and
   diagnostics about splits and instantiations. In trace mode, actions also return
   tactic syntax. `EMatchAction.lean` tracks which theorem instances appear in the
   final proof and then replay-tests a reduced parameter set. Collecting the
   constants a proof uses isn't enough for this, because an instantiation that
   appears nowhere in the proof may still have introduced a term that a later match
   needed. `CollectParams.lean` and the elaborator turn the trace into
   `grind only [...]` suggestions. With `useSorry` enabled, trace mode may fill
   unfinished branches with `sorry`, so a repair tactic has to switch it off.

## What `guard_solve` reuses

| grind component | Used by | What it buys |
| --- | --- | --- |
| `register_grind_attr` | `guard_rule` in `Experimental/Rules.lean` | A scoped, indexed policy-lemma database with grind's usual modifiers |
| `Grind.mkParams`, `elabGrindParams`, `getLiaExtensions` | `GuardSolver.mkParams`, which mirrors the frontend's parameter assembly | Explicit hints, plus a small arithmetic database and structural support |
| `Grind.main` | The symbolic leaves of `guard_solve` | Shared normalization, congruence closure, E-matching, splitting, and arithmetic, order and AC reasoning |
| `withProtectedMCtx` | The whole `guard_solve` attempt | The caller's existential witnesses stay untouched, including during assumption search and computation |
| `Grind.Result.toMessageData` | Failed obligations | The engine's own diagnostics are shown to the user |
| Saved tactic state and `TryThis` | Candidate search | Ordered attempts, rollback, and a replayable proof of the chosen witness |

`guard_solve` tries cheap things first. It looks for a hypothesis that already
proves the goal, then tries `decide` on goals it can compute, then splits explicit
conjunctions, and only sends what's left to the configured grind engine. If
splitting a conjunction fails, it retries the whole conjunction so that a
multipattern rule can match terms from both sides.

The split matters for a goal like
`40 ≤ proposed ∧ (decidePolicy pack frozenContext).allow = true`. The first half
needs a hypothesis and arithmetic; the second is a concrete policy computation that
`decide` can finish. Either way, the full policy predicate stays in the goal,
validation-error gate included.

Out of the box, the rule database contains the equivalence between the runtime
decision and its LeanLTL meaning (`decision_leanLTL_correct`), plus the theorems
that read authorization and error-freedom off an allowed decision (`decision_sound`,
`decision_no_errors`). A policy author can register a proved symbolic
characterization of their own policy with `@[guard_rule =]`, or a forward rule with
`@[guard_rule →]`. A rule's description string is never part of the theorem
database.

The defaults are 4 splits, 3 E-matching rounds per split phase, term generation 6,
and 256 instances per branch, on top of Lean's usual heartbeat and recursion limits.
They keep the search bounded, so the search is incomplete: a candidate that fails is
unproved, and showing it impossible would need a separate proof of the negated goal.
Candidate order expresses the caller's preference and implies nothing about
optimality.

## Regression checks

[Adversarial.lean](../examples/repair/Adversarial.lean) contains one failing
reproducer for each way a proof-search wrapper like this can accept something it
shouldn't, or leave the caller's state broken:

| What the test tries | What `guard_solve` does about it |
| --- | --- |
| A well-typed term whose type is a different proposition | Checks the proof against the goal's expected type |
| A local definition that hides a `sorry` | Closes over the local declarations the proof uses before scanning its dependencies |
| A multipattern rule that needs terms from both conjuncts | Rolls back a failed split and retries the whole conjunction |
| A goal that a hypothesis proves but `decide` would exhaust recursion on | Tries `assumptionCore` before `decide` |
| A discharger that logs an error and then "succeeds" | Captures messages and rejects any attempt that produced an error |
| A case exclusion that only removes rules from the first database | Consolidates case registrations before elaborating each parameter |

In the first case Lean's kernel would still reject the final declaration; the check
in `guard_solve` makes the failure show up at the candidate that caused it.

The last case exists because the pinned `eraseCasesTypes` removes entries only from
extension zero. `guard_solve` still runs `elabGrindParams` on every parameter, and
follows the ordering of `mkGrindParams` for suggestions, local lemmas and anchors.
Consolidating first keeps eager splitting working, and lets later parameters add
databases or bring an excluded rule back.

A single transaction wraps each attempt. It validates a completed proof and restores
the saved state when an attempt fails, including when it fails with a runtime
exception. The tests catch exceptions directly, without relying on tactic
backtracking, and then inspect goals, assignments, declarations and error messages.
They avoid `fail_if_success`, which restores state on its own and would hide a
broken transaction. `scripts/verify.py` runs both regression files together with the
repair and temporal stress suites.

## Limits and possible extensions

* Upstream marks the `grind_propagator` syntax in `Init/Grind/Propagator.lean` as
  not implemented. Builtin propagators exist, but there is no supported way for a
  policy plugin to add one, so proved rules are the extension point.
* Solver extensions have to register during initialization and maintain the engine's
  invariants. A custom temporal solver would need proof reconstruction, and it would
  only be worth writing if theorem instantiation turned out to be inadequate in
  practice. `guard_solve` relies instead on the proved correspondence between the full
  policy and LeanLTL, together with its decidability.
* grind refutes a goal you give it. Its arithmetic models can't synthesize edits, so
  the caller still supplies explicit witness candidates. `guard_solve` never invents
  trusted observations, confirmations, histories, or an optimal edit.
* `guard_rule` keeps its own theorem set, but normalization and symbol priorities are
  shared with every other grind attribute, so it is not a sealed sandbox.
* Each symbolic obligation and each candidate starts from fresh engine state. Theorems
  and normalization setup could be shared, but reusing an equality graph across
  different witnesses would need careful invalidation of dependent facts, so there is
  no cross-candidate cache.
* `guard_repair?` emits the successful `exact ⟨candidate, by guard_solve ...⟩` (or the
  custom discharger) and tests that it replays. It does not minimize the proof. Reusing
  `grind?`'s trace minimizer would mean adopting its replay checks and handling partial
  traces explicitly.
* Custom dischargers are ordinary Lean metaprograms. On failure the transaction
  restores Lean's elaborator state, but it can't undo IO that a user-supplied tactic
  performed.
* Master has already moved away from 4.33.1 in places, for example in homomorphism
  handling and the removal of the old `ToInt` implementation. Importing the pinned APIs
  keeps those representations from mixing and avoids depending on features that exist
  only on master.

Usage and the regression commands are in [the repair guide](../examples/repair/README.md).
