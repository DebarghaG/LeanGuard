import LeanGuard.Experimental.TemporalRepair
import LeanGuard.Audit

/-! Tests for `guard_solve` and `@[guard_rule]`. -/

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

-- Prove this once and register it; repairs can then reason about the allow decision
-- for symbolic amounts without unfolding the evaluator.
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

-- Needs arithmetic, congruence closure and the registered rule together.
theorem aliases_and_arithmetic (a b cap : Nat) (same : a = b) (fits : b + 1 ≤ cap) :
    (decidePolicy (spendPolicy cap) (spendContext (a + 1))).allow = true := by
  guard_solve (splits := 0)

-- One conjunct is arithmetic over a hypothesis; the other is a concrete policy computation.
theorem mixed_obligations (proposed : Nat) (intent : 40 ≤ proposed) :
    ∃ amount, amount ≤ proposed ∧
      (decidePolicy (spendPolicy 40) (spendContext amount)).allow = true := by
  guard_repair? [50, 40]

-- The registered correspondence theorem turns an allow decision into LeanLTL satisfaction.
theorem temporal_bridge (pack : PolicyPack) (ctx : Nat → Context) (candidate : Nat)
    (safe : (decidePolicy pack (ctx candidate)).allow = true) :
    ∃ edit, edit = candidate ∧ (historyTrace (ctx edit).history ⊨ pack.toLeanLTL (ctx edit)) := by
  guard_repair? [candidate]

-- Hints go through grind's own parameter elaborator, so local proof terms work.
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

-- A `local` rule is gone once its section ends.
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

-- `guard_solve` must not solve the goal by assigning the caller's metavariable.
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

-- Every candidate fails; the error lists them in the order given.
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

-- A `sorry` inside an auxiliary theorem is still caught.
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
