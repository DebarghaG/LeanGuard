# Lean metaprogramming for tool-call repair

This opt-in experiment uses Lean's existing tactics to find a compliant candidate
and show an agent the corresponding proof. It imports the actual LeanGuard policy
evaluator. The native server and Python host do not import or invoke this experiment.

Run from the LeanGuard repository root:

```sh
lake build LeanGuard.Experimental.Repair
lake env lean examples/repair/Examples.lean
```

The second command runs the examples, prints diagnostic JSON and proof suggestions,
and runs LeanGuard's existing axiom audit over the example namespace. It needs no
model, backend, or external service. Lean/mathlib versions come from this checkout.

## What it does

`guard_repair? [candidate₁, candidate₂, ...]` expects a goal of the form
`∃ edit, allowedEdit edit ∧ compliant edit`. It tries the candidates in order,
restores the proof state after unsuccessful attempts, and accepts the first fully
proved witness. It emits a standard Lean `Try this` suggestion that an agent can
copy and replay without the repair tactic.

For example, the fixture has already spent 60 against a budget of 100. Its original
call asks to spend 70. `amountContext` changes the amount in the arguments, normalized
request, and current history head together; past events and facts stay fixed.

```lean
theorem budget_repair : ∃ amount : Nat, 0 < amount ∧ amount ≤ 70 ∧
    (decidePolicy budget (amountContext amount)).allow = true := by
  guard_repair? [70, 50, 0, 40]
```

Lean rejects 70 and 50 for exceeding the remaining budget, and 0 because the goal
and policy require a positive amount. It produces:

```lean
exact ⟨40, by decide⟩
```

The examples replay this ordinary proof separately. Compliance here includes the
entire `decidePolicy` result: permits, requirements, forbids, and validation errors.

The default dischargers are `rfl`, `assumption`, `simp_all`, `ring`, `linarith`,
`nlinarith`, `omega`, `decide`, `grind`, and `aesop`. These are reused from Lean and
the project's existing dependencies. No new decision procedure is implemented.
See the [Lean tactic reference](https://lean-lang.org/doc/reference/latest/Tactic-Proofs/Tactic-Reference/)
and [TryThis API](https://lean-lang.org/doc/api/Lean/Meta/Tactic/TryThis.html).

Use `using` to replace that cascade with a domain-specific proof, for example
`using (simp [myPolicy, myContext]; omega)`. Symbolic candidates work too:

```lean
theorem symbolic_budget_repair (spent cap proposed : Nat)
    (available : spent ≤ cap) (oversized : cap ≤ spent + proposed) :
    ∃ amount : Nat, amount ≤ proposed ∧ spent + amount = cap := by
  guard_repair? [proposed, cap - spent] using omega
```

That example emits `exact ⟨cap - spent, by omega⟩`. This is a reusable arithmetic
lemma; applying it to a different policy still requires proving the connection
between that policy and the arithmetic constraints.

## Showing an agent what is missing

`#guard_explain pack context` prints the real decision together with descriptions
and check names for blocked rules, plus the applicable permit rules. It preserves
the decision's errors, evidence IDs, and default-deny reason. For the existing
document policy and a write with no preceding evidence, it reports:

| Failed rule | Existing policy description |
| --- | --- |
| `documents.read_before_write` | read within one hour |
| `documents.confirm` | one-use, unrevoked user approval |

An agent can use this to identify the required read and trusted confirmation flow,
then retry against a fresh snapshot. The descriptions are policy-author guidance;
they are not proofs that a proposed sequence of actions will succeed. A separate
theorem, `write_amount_cannot_repair`, proves that **every** amount is denied in this
fixed context. That is an impossibility result for this edit family, independently
of the tactic's finite search.

## Scope of the experiment

- Candidate values or templates are supplied explicitly, with at most 32 candidates.
  The first proved candidate wins; order them by preference. There is no automatic
  extraction of repairs from arbitrary Lean `Check.run` functions, nor an optimality
  guarantee. Ordinary Lean heartbeat limits still apply.
- The goal is the edit contract. Keep identity, action, resource, trusted facts,
  approval bindings, and past events fixed unless the task explicitly models an
  authorized change. The tactic itself is a generic existential-witness search
  and does not enforce those restrictions independently of the goal.
- A smaller amount is useful only if the task permits it. The fixture explicitly
  allows a positive reduction. Exact-amount requests need a different contract;
  compliance alone does not establish task success or user consent.
- A failed search means no supplied candidate was proved by the selected tactics.
  It is not a proof that repair is impossible. Custom dischargers are trusted Lean
  metaprograms, subject to the same execution assumptions as other local tactics.
- Successful attempts must close the goal without unresolved metavariables or a
  direct `sorry`. The example audit also checks transitive axioms, allowing only
  `propext`, `Classical.choice`, and `Quot.sound`. The default cascade uses `decide`;
  it does not use `native_decide` or introduce additional proof axioms.
- This is offline, elaboration-time assistance. A live integration would export a
  frozen decision context, search over permitted edits, return the candidate and
  proof to the agent, then use the existing host to obtain a fresh authoritative
  snapshot, normalize arguments, obtain any required new confirmation, and recheck
  admission. The proof does not replace host validation, schema checking, or dispatch.

A live follow-up can compare existing denial feedback against these rule
explanations and certified candidate suggestions, starting agents from the same
saved contexts. Measure repeated denials and task success separately from offline
proof success and search cost. Domain-specific candidate templates and
simplification lemmas can then be added where the examples show a benefit.

## Saved-rollout contracts

`LeanGuard.Experimental.RecordedRepair` supplies two contracts for offline replay:
`lookupRepair` replaces a read-only lookup ID with the customer identity in the
recorded facts, while `documentPlanSafe` checks a proposed sequence against the
existing deterministic document fixture. Both retain the supplied past events.
The document contract also fixes the requested resource, value, and approval;
its assumption that admitted calls succeed belongs to that synthetic fixture.

Build these helpers with `lake build LeanGuard.Experimental.RecordedRepair`.
The saved-rollout inventory, candidate screening, per-case Lean certificates,
and results live in the separate private `LeanGuard-Training` workspace under
`scripts/experiments/repair_*.py` and `results/repair-evaluation-20260911/`.
Those experiments distinguish repairs before execution from continuations after
a denial, and distinguish native screening from Lean kernel certification.
