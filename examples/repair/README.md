# Suggesting repairs with Lean

`guard_repair?` finds a permitted, policy-compliant edit among candidates you supply
and prints a Lean proof that an agent can reuse. It is an experimental proof-authoring
tool; call execution still goes through the normal LeanGuard host.

Run the [examples](Examples.lean) from the repository root:

```sh
lake build LeanGuard.Experimental.Repair
lake env lean examples/repair/Examples.lean
```

## Define the permitted change

State both the user's intent and policy compliance in an existential goal. In this
example, the task permits reducing a positive spend. The account has already spent
60 of its 100-unit budget, and the proposed amount is 70:

```lean
theorem budget_repair : ∃ amount : Nat, 0 < amount ∧ amount ≤ 70 ∧
    (decidePolicy budget (amountContext amount)).allow = true := by
  guard_repair? [70, 50, 0, 40]
```

The tactic selects 40 and suggests `exact ⟨40, by decide⟩`. `amountContext` updates
the proposed amount and its encoding while preserving trusted facts and past events.
The definitions are in [Examples.lean](Examples.lean).

Order candidates by preference; the first proved candidate wins. Supply at most 32.
A failed search means none of those candidates was proved, not that repair is
impossible. If the user requires an exact amount, encode that requirement instead
of allowing a reduction.

The tactic tries existing Lean/mathlib automation. Use `using` when a specific
solver or policy lemma is appropriate:

```lean
theorem remaining_budget (spent cap proposed : Nat)
    (available : spent ≤ cap) (oversized : cap ≤ spent + proposed) :
    ∃ amount : Nat, amount ≤ proposed ∧ spent + amount = cap := by
  guard_repair? [proposed, cap - spent] using omega
```

## Explain a denial

`#guard_explain pack context` prints the decision, blocked rule descriptions, and
check names. An agent can use this to identify a required read or confirmation.
Descriptions are guidance; a suggested action still needs admission against a
fresh authoritative snapshot.

Give agents structured candidate arguments alongside the explanation. If an agent
rewrites those arguments, validate the resulting call and check admission again.

Keep trusted identity, facts, approval evidence, and past events fixed. A proof of
policy compliance establishes only the intent restrictions written in the goal.
Missing observations or approval must come from the host's trusted flows.

## Use LeanLTL policy goals

Import `LeanGuard.Experimental.TemporalRepair` to state compliance directly as
LeanLTL satisfaction:

```lean
import LeanGuard.Experimental.TemporalRepair
open LeanGuard LeanGuard.Experimental

example (pack : PolicyPack) (context : α → Context) (allowedEdit : α → Prop)
    (candidate : α) (intent : allowedEdit candidate)
    (safe : historyTrace (context candidate).history ⊨ pack.toLeanLTL (context candidate)) :
    ∃ edit, allowedEdit edit ∧
      (historyTrace (context edit).history ⊨ pack.toLeanLTL (context edit)) := by
  guard_repair? [candidate] using exact ⟨intent, safe⟩
```

The complete policy goal includes validation errors. Its valid repairs are the
same as those for the native allow decision. Use the full policy goal when a
single temporal condition would omit other requirements.

These proofs concern the supplied history. New events can revoke approval or
consume a budget, so a previously proved repair needs a fresh admission check.
LeanGuard's trace runs toward the past; this interface does not establish future
task completion or arbitrary infinite-trace liveness. See the
[LeanLTL guide](../../docs/leanltl.md) for the semantics.

The [temporal examples](TemporalStress.lean) cover ordering, windows, scope,
revocation, and proof reuse. Run them with:

```sh
lake build LeanGuard.Experimental.TemporalRepair
lake env lean examples/repair/TemporalStress.lean
```

The [Dogwood examples](../dogwood/README.md#repair-experiments) include both a
quantity repair and proofs that specified repair contracts are impossible.
