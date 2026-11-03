import LeanGuard.Experimental.TemporalRepair
import LeanGuard.Audit

namespace LeanGuard.Experimental.Adversarial
open Lean Meta Elab Tactic

-- Some tests here fail on purpose or inspect state, so later tactics are unreachable or unused.
set_option linter.unreachableTactic false
set_option linter.unusedTactic false

-- A term can type-check and still prove the wrong goal.
run_cmd Command.liftTermElabM do
  let goal ← mkFreshExprSyntheticOpaqueMVar (mkConst ``False)
  goal.mvarId!.assign (mkConst ``True.intro)
  let accepted ← try
    GuardSolver.checkProof goal.mvarId!
    pure true
  catch _ => pure false
  if accepted then throwError "accepted a proof of True as a proof of False"

run_cmd Command.liftTermElabM do
  let type := mkConst ``True
  withLetDecl `hidden type (← mkSorry type true) fun hidden => do
    let goal ← mkFreshExprSyntheticOpaqueMVar type
    goal.mvarId!.assign hidden
    let accepted ← try
      GuardSolver.checkProof goal.mvarId!
      pure true
    catch _ => pure false
    if accepted then throwError "accepted sorry hidden in a local definition"

def leftPredicate (n : Nat) : Prop := n = n
def rightPredicate (n : Nat) : Prop := n = n

theorem paired (n m : Nat) : leftPredicate n ∧ rightPredicate m := ⟨rfl, rfl⟩

section
local grind_pattern [guard_rule] paired => leftPredicate n, rightPredicate m

-- Neither predicate alone contains the two terms needed to instantiate `paired`.
theorem multipattern_conjunction (n m : Nat) : leftPredicate n ∧ rightPredicate m := by
  guard_solve
end

-- A hypothesis already proves this; `decide` would run out of recursion depth.
set_option maxRecDepth 128 in
theorem existing_evidence (h : (List.replicate 10000 true).all id = true) :
    (List.replicate 10000 true).all id = true := by
  guard_solve

-- Checking a proof must not assign the caller's metavariables.
run_cmd Command.liftTermElabM do
  let type ← mkFreshExprMVar (mkSort Level.zero)
  let goal ← mkFreshExprSyntheticOpaqueMVar type
  goal.mvarId!.assign (mkConst ``True.intro)
  let accepted ← try
    GuardSolver.checkProof goal.mvarId!
    pure true
  catch _ => pure false
  if accepted || (← type.mvarId!.isAssigned) then
    throwError "proof validation solved an unknown goal type"

theorem logged_errors_are_failures : ∃ amount : Nat, amount = 40 := by
  fail_if_success
    guard_repair? [40] using
      run_tac Lean.logError "discharger reported an error"
      rfl
  exact ⟨40, rfl⟩

set_option trace.guard.repair true in
/--
trace: [guard.repair] Candidate 0:
    discharger reported errors:
    logged error on candidate zero
-/
#guard_msgs (trace, drop info) in
example : ∃ amount : Nat, amount ≤ 40 := by
  guard_repair? [0, 40] using
    try
      guard_target = 0 ≤ 40
      run_tac logError "logged error on candidate zero"
    decide

theorem malformed_config_is_failure : True := by
  fail_if_success guard_solve (splits := "not a number")
  fail_if_success guard_solve [does_not_exist]
  trivial

theorem reverse_temporal_bridge (pack : PolicyPack) (ctx : Context)
    (safe : historyTrace ctx.history ⊨ pack.toLeanLTL ctx) :
    (decidePolicy pack ctx).allow = true := by
  guard_solve

theorem forward_policy_facts (pack : PolicyPack) (ctx : Context)
    (safe : (decidePolicy pack ctx).allow = true) :
    authorize pack.rules (atomValue ctx) ctx.request.action ctx.history = true ∧
      validationErrors pack ctx = [] := by
  guard_solve

-- Catch the error without TacticM's backtracking, so the tactic has to roll itself back.
theorem transaction_rollback : True := by
  run_tac
    let goal ← getMainGoal
    let goals ← getGoals
    let injected ← mkAuxDeclName `failedAuxiliary
    for resource in [false, true] do
      let caught ← tryCatchRuntimeEx (do
        GuardSolver.runChecked goal do
          goal.assign (mkConst ``True.intro)
          setGoals []
          addDecl <| .thmDecl {
            name := injected, levelParams := [], type := mkConst ``True
            value := mkConst ``True.intro
          }
          logError "a failed attempt must not retain this message"
          if resource then throwMaxRecDepthAt (← getRef)
          else throwError "ordinary failure"
        pure false) fun ex => do
          if resource != ex.isMaxRecDepth then throw ex
          pure true
      if !caught || (← goal.isAssigned) || (← getGoals) != goals ||
          (← getEnv).contains injected || (← Core.getMessageLog).hasErrors then
        throwError "failed transaction leaked proof state, goals, declarations, or errors"
  trivial

-- When grind throws, it admits its temporary goal first. Check that we still roll back.
theorem protected_failure_rollback : True := by
  run_tac
    let goal ← getMainGoal
    let caught ← tryCatchRuntimeEx (do
      GuardSolver.runChecked goal do
        Grind.withProtectedMCtx GuardSolver.defaultConfig goal fun _ => do
          throwMaxRecDepthAt (← getRef)
      pure false) fun ex => do
        unless ex.isMaxRecDepth do throw ex
        pure true
    if !caught || (← goal.isAssigned) then throwError "protected goal leaked an assignment"
  trivial

theorem abstract_proof (n m : Nat) (h : n ≤ m) : n ≤ m + 1 := by
  guard_solve +abstractProof

theorem local_proof_hint (n : Nat) (h : ∀ n, leftPredicate n) : leftPredicate n := by
  guard_solve [(h n)]

section
attribute [local guard_rule ←] paired

theorem exclude_theorem (n m : Nat) : leftPredicate n ∧ rightPredicate m := by
  fail_if_success guard_solve [-paired]
  guard_solve
end

inductive Choice where | first | second

section
attribute [local guard_rule cases] Choice

theorem exclude_cases (x : Choice) : x = .first ∨ x = .second := by
  fail_if_success guard_solve [-Choice]
  fail_if_success guard_solve [guard_rule, -Choice]
  guard_solve [-Choice, cases Choice]

theorem readd_cases (x : Choice) : x = .first ∨ x = .second := by
  guard_solve [-Choice, guard_rule]

theorem eager_cases (x : Choice) : x = .first ∨ x = .second := by
  guard_solve [cases eager Choice, guard_rule, (True.intro)]

theorem default_cases (x : Choice) : x = .first ∨ x = .second := by
  guard_solve
end

-- A bad argument should fail here and leave the caller's goal as it was.
theorem repair_input_errors : ∃ n : Nat, n = 40 := by
  fail_if_success guard_repair? []
  fail_if_success guard_repair? [40] with [] using rfl
  fail_if_success guard_repair? (splits := 0) [40] using rfl
  fail_if_success guard_repair? [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
    16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 40]
  exact ⟨40, rfl⟩

run_cmd
  LeanGuard.Audit.check #[``multipattern_conjunction, ``transaction_rollback]
    #[`LeanGuard.Experimental.Adversarial]

end LeanGuard.Experimental.Adversarial
