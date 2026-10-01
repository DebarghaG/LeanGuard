import LeanGuard.Experimental.TemporalRepair
import LeanGuard.Audit

/-! Regression examples for the policy-specific grind integration. -/

namespace LeanGuard.Experimental.GrindExamples
open Lean

def spendContext (amount : Nat) : Context := {
  request := {
    id := "spend", kind := "request", time := 0, principal := "alice", session := "grind"
    action := "spend", resource := "account", binding := "", amount := amount
  }
  arguments := Json.null
  facts := Json.null
  history := []
}

def spendPolicy (cap : Nat) : PolicyPack := { name := "symbolic-spend", rules := [
  permit "spend" ["spend"],
  require "cap" ["spend"]
    (check "amount" fun ctx ↦ .ok (ctx.request.amount ≤ cap)) "within budget"
] }

-- A policy author proves this once. Repairs then reason about the full allow decision
-- without unfolding the policy evaluator for every symbolic candidate.
@[guard_rule =]
theorem spendPolicy_correct (cap amount : Nat) :
    (decidePolicy (spendPolicy cap) (spendContext amount)).allow = true ↔ amount ≤ cap := by
  simp [spendPolicy, spendContext, decidePolicy, authorize, permitted, requirementsMet, forbidden,
    validationErrors, evaluationErrors, atomValue, evaluate, permit, require, check,
    Rule.applies, Except.toOption]

theorem symbolic_policy_repair (spent cap proposed : Nat)
    (available : spent ≤ cap) (oversized : cap ≤ spent + proposed) :
    ∃ amount, amount ≤ proposed ∧ spent + amount = cap ∧
      (decidePolicy (spendPolicy cap) (spendContext (spent + amount))).allow = true := by
  guard_repair? [proposed, cap - spent]

theorem symbolic_policy_replay (spent cap proposed : Nat)
    (available : spent ≤ cap) (oversized : cap ≤ spent + proposed) :
    ∃ amount, amount ≤ proposed ∧ spent + amount = cap ∧
      (decidePolicy (spendPolicy cap) (spendContext (spent + amount))).allow = true := by
  exact ⟨cap - spent, by guard_solve⟩

-- Arithmetic, congruence closure, and the registered policy equivalence cooperate.
theorem aliases_and_arithmetic (a b cap : Nat) (same : a = b) (fits : b + 1 ≤ cap) :
    (decidePolicy (spendPolicy cap) (spendContext (a + 1))).allow = true := by
  guard_solve (splits := 0)

-- A symbolic edit restriction and a concrete policy computation need different reasoning.
theorem mixed_obligations (proposed : Nat) (intent : 40 ≤ proposed) :
    ∃ amount, amount ≤ proposed ∧
      (decidePolicy (spendPolicy 40) (spendContext amount)).allow = true := by
  guard_repair? [50, 40]

-- The registered full-policy bridge transports runtime evidence into LeanLTL automatically.
theorem temporal_bridge (pack : PolicyPack) (ctx : Nat → Context) (candidate : Nat)
    (safe : (decidePolicy pack (ctx candidate)).allow = true) :
    ∃ edit, edit = candidate ∧ (historyTrace (ctx edit).history ⊨ pack.toLeanLTL (ctx edit)) := by
  guard_repair? [candidate]

-- Explicit hints use grind's real parameter elaboration, including local proof terms.
def permittedEdit (n : Nat) : Prop := n % 2 = 0

theorem even_permitted (n : Nat) : permittedEdit (2 * n) := by
  simp [permittedEdit]

theorem explicit_hint (n : Nat) : ∃ edit, edit = 2 * n ∧ permittedEdit edit := by
  guard_repair? (splits := 0) [2 * n] with [even_permitted]

theorem explicit_hint_replay (n : Nat) : ∃ edit, edit = 2 * n ∧ permittedEdit edit := by
  exact ⟨2 * n, by guard_solve (splits := 0) [even_permitted]⟩

theorem instantiation_budget (n : Nat) : permittedEdit (2 * n) := by
  fail_if_success guard_solve (instances := 0) [even_permitted]
  guard_solve [even_permitted]

-- Scoped policy rules must not leak after their section ends.
section
attribute [local guard_rule ←] even_permitted

theorem local_rule (n : Nat) : permittedEdit (2 * n) := by guard_solve
end

theorem local_rule_does_not_leak (n : Nat) : permittedEdit (2 * n) := by
  fail_if_success guard_solve
  exact even_permitted n

section
attribute [local grind ←] even_permitted

theorem default_grind_rules_are_separate (n : Nat) : permittedEdit (2 * n) := by
  fail_if_success guard_solve
  grind
end

section
local grind_pattern [guard_rule] even_permitted => permittedEdit (2 * n)

theorem explicit_pattern (n : Nat) : permittedEdit (2 * n) := by guard_solve
end

theorem partial_trace_rejected : True := by
  fail_if_success
    have : False := by guard_solve +trace +useSorry
  trivial

theorem candidate_type_error_is_local : ∃ amount : Nat, amount = 40 := by
  guard_repair? ["wrong type", 40]

theorem solver_siblings : (1 = 1) ∧ True := by
  constructor
  · guard_solve
  · trivial

-- The symbolic solver must not pick an unresolved witness belonging to its caller.
theorem caller_metavariable_preserved : ∃ amount : Nat, amount = 40 := by
  refine ⟨?_, ?_⟩
  swap
  fail_if_success guard_solve
  swap
  exact 40
  rfl

/-- info: Try this:
  [apply] exact ⟨50, by guard_solve⟩ -/
#guard_msgs in
example : ∃ amount : Nat, amount ≤ 70 := by
  guard_repair? [50, 40]

-- The same candidate ordering applies when there is no successful witness.
set_option linter.unreachableTactic false in
/--
error: guard_repair? could not prove any supplied candidate.
This is not a proof that repair is impossible. Inspect #guard_explain, supply other candidates, or use `using` with policy-specific lemmas. Missing trusted observations must be obtained through the host.

Candidate 70:
deliberate discharger failure
⊢ 70 = 40

Candidate 50:
deliberate discharger failure
⊢ 50 = 40
-/
#guard_msgs in
example : ∃ amount : Nat, amount = 40 := by
  guard_repair? [70, 50] using fail "deliberate discharger failure"

set_option linter.unreachableTactic false in
theorem incomplete_custom_rejected : ∃ amount : Nat, amount = 40 := by
  fail_if_success guard_repair? [40] using skip
  fail_if_success guard_repair? [40] using sorry
  exact ⟨40, rfl⟩

-- An auxiliary theorem must not hide a partial proof from validation.
open Lean.Elab.Tactic Lean.Meta in
elab "hidden_sorry_for_test" : tactic => do
  let goal ← getMainGoal
  let type ← goal.getType
  let proof ← mkAuxTheorem type (← mkSorry type true)
  goal.assign proof
  replaceMainGoal []

set_option linter.unreachableTactic false in
theorem hidden_sorry_rejected : ∃ amount : Nat, amount = 40 := by
  fail_if_success guard_repair? [40] using hidden_sorry_for_test
  exact ⟨40, rfl⟩

run_cmd
  LeanGuard.Audit.check #[``symbolic_policy_repair, ``temporal_bridge]
    #[`LeanGuard.Experimental.GrindExamples]

end LeanGuard.Experimental.GrindExamples
