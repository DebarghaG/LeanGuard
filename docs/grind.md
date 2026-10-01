# Borrowing grind for policy reasoning

This investigation follows Lean master at
[`3baf82028468b3529ca83b20393596ec86828df6`](https://github.com/leanprover/lean4/tree/3baf82028468b3529ca83b20393596ec86828df6),
dated 2026-09-23, and checks the integration against LeanGuard's pinned Lean **4.33.1**
(`819816b2e0a3bf405af45ae5c7af2491d8f5bee6`). The implementation imports the pinned
engine; it does not vendor source from master. These are internal Lean APIs, so a
toolchain upgrade needs the repair regression suite.

## Where the implementation lives

[`Init/Grind`](https://github.com/leanprover/lean4/tree/3baf82028468b3529ca83b20393596ec86828df6/src/Init/Grind)
is the logical foundation, not the search engine. `Norm.lean` supplies normalization
equalities; `Lemmas.lean`, `Cases.lean`, and the arithmetic modules supply proof-building
lemmas. `Ring`, `Module`, `Ordered`, `Order`, and `AC` specify the algebraic laws the
solvers require. Syntax and configuration also live here. These laws justify generated
proofs; recognizing an operator's name alone does not justify reasoning about it.

The engine is in
[`Lean/Meta/Tactic/Grind`](https://github.com/leanprover/lean4/tree/3baf82028468b3529ca83b20393596ec86828df6/src/Lean/Meta/Tactic/Grind).
The frontend is in
[`Lean/Elab/Tactic/Grind`](https://github.com/leanprover/lean4/tree/3baf82028468b3529ca83b20393596ec86828df6/src/Lean/Elab/Tactic/Grind).
Reading only `Init/Grind` misses theorem indexing, the equality graph, search control,
and proof reconstruction.

## One goal through the engine

1. **Elaborate parameters.** `Elab/Tactic/Grind/Main.lean::mkGrindParams` assembles a
   `Grind.Params`: configuration, theorem extensions, explicit facts and lemmas,
   normalization context, simprocs, symbol priorities, and optional anchors.
   `Param.lean` handles theorem directions, local proof terms, definitions' equation
   theorems, extension names, and exclusions. Parameter elaboration is reusable.

2. **Protect the surrounding proof.** `Meta/Tactic/Grind/Main.lean::withProtectedMCtx`
   creates a fresh goal at a new metavariable depth. Definitional equality tests cannot
   opportunistically assign metavariables belonging to the caller. It resolves internal
   delayed assignments before returning the proof. Its exception path admits the
   temporary goal and rethrows: a speculative caller must restore its saved state on
   failure. A successful call alone is insufficient if other obligations remain.

3. **Normalize and internalize.** `initCore` unfolds reducible definitions, beta-reduces,
   and processes hypotheses; `assertExtra` adds explicit facts and activates lemmas.
   `Simp.lean::preprocessImpl` uses grind's normalizer, then canonicalizes projections,
   nested proofs, universe levels, and shared expressions. Rewrite proofs are composed
   with `Eq.mp`. The normalizer's discharger deliberately avoids assumptions so its
   cache remains valid across search branches. This is different from repeatedly
   invoking `simp_all`.

4. **Maintain a proof-producing equality graph.** `Types.lean::ENode` and `GoalState`
   retain equivalence classes, parent links, congruence tables, generations, pending
   facts, splitting state, and each theory solver's state. `Internalize.lean` registers
   terms and opportunities for propagation. `Core.lean` merges classes, removes and
   reinserts affected parents, and wakes propagators and solvers. Proof edges record
   why terms are equal. Proposition truth is represented by equality with `True` or
   `False`; equating those closes the goal. Some congruence proofs are delayed until
   needed, with distinct markers for ordinary and symmetric equality congruence.

5. **Instantiate relevant lemmas.** `Theorems.lean` indexes lemmas by symbols in their
   patterns. A lemma activates when the required symbols occur, rather than scanning
   every theorem for every fact. `EMatchTheorem.lean` infers normalized patterns;
   `EMatch.lean` matches them modulo known equalities, supports multipatterns, supplies
   typeclass arguments, and constructs actual applications of the original theorem.
   Instance deduplication and modification times avoid repeated work. New terms get
   higher generations, so `gen`, `genLocal`, `instances`, and `ematch` bound different
   sources of growth. Explicit `grind_pattern` constraints can delay an instance until
   a guard is known or restrict term depth, size, or instance count.

6. **Coordinate theory solvers.** `SolverExtension` supplies hooks for internalization,
   new equalities/disequalities, solver actions, and model-based theory combination.
   `Solvers.mkActionCore` combines solver actions, and `Solvers.mkAction` drains their
   pending facts. Arithmetic, order, and AC solvers exchange proved facts through the
   same graph. Cutsat's proof builder reconstructs a Lean proof from its derivation,
   tracking only relevant variables and polynomials; a solver model is not a proof.

7. **Schedule search.** `Finish.lean::Action.mkFinish` builds:

   ```text
   intros; assertAll;
   repeat (theory solvers <|> instantiate <|> splitNext <|> mbtc)
   ```

   This is not ordinary tactic backtracking. `Action` has separate continuations for
   inapplicability and progress; `<|>` tries the right action only when the left is
   inapplicable. An action can run the remaining search on several branches and inspect
   their proofs. `Split.lean::splitCore` implements non-chronological backtracking:
   when a branch's contradiction does not use its case assumption, it closes the
   unsplit goal directly. `splits` bounds branch search, not all normalization work.

8. **Report or replay.** `Grind.Result` retains a stuck goal, issues, counters, and
   split/instantiation diagnostics. In trace mode, actions also return tactic syntax.
   `EMatchAction.lean` tracks theorem-instance markers in the resulting proof, then
   replay-tests a reduced set of parameters. Merely collecting constants used by the
   proof is not sufficient: an otherwise unused instantiation may introduce terms
   needed by later matching. `CollectParams.lean` and the elaborator turn the trace
   into `grind only [...]` suggestions. Trace mode can insert `sorry` on unfinished
   branches when `useSorry` is enabled, so a repair tactic must disable it.

## What LeanGuard reuses

| Component | Integration | Benefit |
| --- | --- | --- |
| `register_grind_attr` | `guard_rule` in `Experimental/Rules.lean` | Scoped, indexed policy lemma registration with grind's existing modifiers |
| `Grind.mkParams`, `elabGrindParams`, `getLiaExtensions` | `GuardSolver.mkParams` follows the frontend's parameter assembly | Explicit hints plus a small arithmetic database and structural support |
| `Grind.main` | Symbolic leaves of `guard_solve` | Shared normalization, congruence closure, E-matching, splitting, arithmetic, order, and AC reasoning |
| `withProtectedMCtx` | The entire `guard_solve` attempt | Isolation from surrounding existential witnesses, including during assumption search and computation |
| `Grind.Result.toMessageData` | Failed obligations | Actual engine diagnostics instead of silently swallowing every exception |
| Saved tactic state and `TryThis` | Candidate search | Ordered attempts, rollback, and a replayable proof of the chosen witness |

The old default made up to ten unrelated tactic attempts per candidate. The new
default first uses existing hypotheses, then computes decidable goals, decomposes
conjunctions when needed, and sends symbolic obligations to this configured engine.
If decomposition fails, it retries the unsplit conjunction so multipattern rules
can match terms from both sides. Decomposition matters for a goal
such as `40 ≤ proposed ∧ (decidePolicy pack frozenContext).allow = true`: one conjunct
needs a hypothesis and arithmetic, while the other is a concrete policy computation.
The full policy predicate, including its validation-error gate, stays in the goal.

The default database includes the full decision/LeanLTL equivalence and the existing
theorems extracting authorization and error-freedom from an allowed decision. A
policy author can add a proved symbolic characterization of their own policy with
`@[guard_rule =]`, or a forward rule with `@[guard_rule →]`. A rule's description
string never enters the theorem database as evidence.

The default limits are four splits, three E-matching rounds per split phase, term
generation six, and 256 instances per branch. Lean's heartbeat and recursion limits
still apply. This bounds search without suggesting it is complete. Failed candidates
are **unproved**, not certified impossible; a negated repair theorem remains a separate
proof obligation. Candidate order expresses preference, not optimality.

## Adversarial audit

The audit found and repaired six defects, each with a failing reproducer in
[Adversarial.lean](../examples/repair/Adversarial.lean):

| Defect | Correction |
| --- | --- |
| A well-typed term for the wrong proposition passed validation | Check the proof against the goal's expected type |
| A used local definition could hide `sorry` | Close over used local declarations before inspecting proof dependencies |
| Conjunction decomposition prevented cross-conjunct multipatterns | Roll back failed decomposition and try the whole conjunction |
| Computation exhausted recursion even when a hypothesis already proved the goal | Try `assumptionCore` before `decide` |
| A discharger that logged an error could still be accepted | Capture messages and reject error-producing attempts |
| Case exclusions silently left rules in secondary databases | Consolidate case registrations before each parameter is elaborated |

Wrong-type acceptance was a frontend validation defect; Lean's final kernel check
still rejected such a declaration.

The last correction is needed because the pinned `eraseCasesTypes` only removes
entries from extension zero. The adapter still uses `elabGrindParams` for every
parameter and follows `mkGrindParams`' ordering for suggestions, local lemmas, and
anchors. Consolidation preserves eager splitting and supports subsequent database
parameters and reintroduction of excluded rules.

One shared transaction validates completed proofs and restores failed attempts,
including runtime exceptions. Direct tests catch exceptions without tactic
backtracking and check goals, assignments, declarations, and error messages.
Repeated recursive proof validation and redundant exception checks were removed.
Tests for failure rollback that relied on `fail_if_success` were replaced with these
direct checks; that combinator restores state itself and can mask a broken transaction.
The verification script runs both regression files and the existing repair/stress suites.

## Boundaries and later extensions

* The public-looking `grind_propagator` syntax is explicitly marked **not implemented**
  in upstream `Init/Grind/Propagator.lean`. Builtin propagators exist, but they are not
  a supported external policy-plugin surface. Use proved rules first.
* Solver extensions must register during initialization and maintain engine invariants.
  A custom temporal solver would need proof reconstruction and measured evidence that
  theorem instantiation is inadequate. The current adapter uses the existing proved
  full-policy correspondence and decidability instead.
* `grind` is chiefly a refutation engine for a supplied goal. Its arithmetic models
  are not an edit synthesizer. This change retains explicit witness candidates; it
  does not invent trusted observations, confirmations, histories, or optimal edits.
* The theorem sets are separated, but upstream normalization and symbol priorities
  are shared between grind attributes. `guard_rule` is not a hermetic solver sandbox.
* Engine state is fresh for each symbolic obligation and candidate. Sharing theorems
  and normalization setup is possible, but reusing an equality graph across changed
  witnesses would require careful dependency invalidation. There is no cross-candidate
  cache here.
* We emit the successful `exact ⟨candidate, by guard_solve ...⟩` (or custom discharger)
  and test replay. We do not claim minimal proofs or reuse `grind?`'s trace minimizer
  yet. That would require its replay checks and explicit handling of partial traces.
* Custom dischargers are ordinary Lean metaprograms. The transaction restores Lean's
  saved elaborator state, not external IO performed by user-supplied tactics.
* Master already differs from 4.33.1, including homomorphism handling and removal of
  the former `ToInt` implementation. Importing the pinned APIs avoids mixing those
  representations or assuming master-only features exist in LeanGuard.

Usage and regression commands are in [the repair guide](../examples/repair/README.md).
