import LeanGuard.Experimental.Repair
import LeanGuard.Examples
import LeanGuard.Audit

/-!
# Repair experiments against native LeanGuard decisions

Run with `lake env lean examples/repair/Examples.lean` after building
`LeanGuard.Experimental.Repair`. These are offline fixtures, not host events.
-/

namespace LeanGuard.Experimental.Examples
open Lean

def request : Event := {
  id := "candidate", time := 100, kind := "request", principal := "alice",
  session := "repair-demo", action := "spend", resource := "account", binding := ""
}

def pastSpend : Event := {
  request with
  id := "past", time := 90, kind := "dispatch", amount := 60
  inputJson := (Json.mkObj [("amount", toJson (60 : Nat))]).compress
}

def budget : PolicyPack := { name := "repair-budget", rules := [
  permit "spend.tools" ["spend"],
  require "spend.quota" ["spend"] (quota 10 100 3600) "at most 100 in the window",
  require "spend.amount" ["spend"] (check "normalized_amount" fun c ↦ do
    let amount ← Data.nat c.arguments "amount"
    return amount > 0 && amount == c.request.amount) "positive, faithfully normalized amount"
] }

/-- Only the amount and its input encoding vary. The historical dispatch and facts stay fixed.
This fixture models normalization for this one tool; a live host must normalize again. -/
def amountContext (amount : Nat) : Context :=
  let arguments := Json.mkObj [("amount", toJson amount)]
  let event := { request with amount := amount, inputJson := arguments.compress }
  ⟨event, arguments, Json.mkObj [], [event, pastSpend]⟩

theorem original_denied : (decidePolicy budget (amountContext 70)).allow = false := by decide

#guard_explain budget (amountContext 70)

-- The first two candidates fail. Zero cannot satisfy the positive-amount requirement.
-- The goal also states the intent restriction: do not increase the proposed amount.
theorem budget_repair : ∃ amount : Nat, 0 < amount ∧ amount ≤ 70 ∧
    (decidePolicy budget (amountContext amount)).allow = true := by
  guard_repair? [70, 50, 0, 40]

-- This is the ordinary proof emitted for the successful candidate, independently replayed.
theorem budget_repair_replayed : ∃ amount : Nat, 0 < amount ∧ amount ≤ 70 ∧
    (decidePolicy budget (amountContext amount)).allow = true := by
  exact ⟨40, by decide⟩

-- Reusable arithmetic templates can be symbolic, with hypotheses rather than concrete data.
theorem symbolic_budget_repair (spent cap proposed : Nat)
    (available : spent ≤ cap) (oversized : cap ≤ spent + proposed) :
    ∃ amount : Nat, amount ≤ proposed ∧ spent + amount = cap := by
  guard_repair? [proposed, cap - spent] using omega

-- Search failure must restore the original goal so other tactics can continue.
theorem failed_search_restores_goal : ∃ amount : Nat, amount = 40 := by
  fail_if_success guard_repair? [70, 50]
  exact ⟨40, rfl⟩

-- An unfinished discharger or a sorry must never count as a proved candidate.
set_option linter.unreachableTactic false in
theorem unproved_candidate_rejected : ∃ amount : Nat, amount = 40 := by
  fail_if_success guard_repair? [40] using skip
  fail_if_success guard_repair? [40] using sorry
  exact ⟨40, rfl⟩

-- The tactic should only solve its main goal, preserving any sibling goals.
theorem sibling_goals_preserved : (∃ amount : Nat, amount = 40) ∧ True := by
  constructor
  · guard_repair? [40]
  · trivial

def writeAmountContext (amount : Nat) : Context :=
  let arguments := Json.mkObj [("amount", toJson amount)]
  let event := { request with
    action := "write", resource := "document", amount := amount,
    inputJson := arguments.compress }
  ⟨event, arguments, Json.mkObj [], [event]⟩

def writeContext : Context := writeAmountContext 0

#guard_explain LeanGuard.Examples.documents writeContext

theorem write_needs_evidence :
    (decidePolicy LeanGuard.Examples.documents writeContext).reasons =
      ["documents.read_before_write", "documents.confirm"] := by decide

-- This proves impossibility for every amount in this fixed context, independently of search.
theorem write_amount_cannot_repair (amount : Nat) :
    (decidePolicy LeanGuard.Examples.documents (writeAmountContext amount)).allow = false := by
  rfl

-- Candidate search must also fail for this denied write.
set_option linter.unreachableTactic false in
theorem denied_write_search_fails : True := by
  fail_if_success
    have : ∃ amount : Nat,
        (decidePolicy LeanGuard.Examples.documents (writeAmountContext amount)).allow = true := by
      guard_repair? [0, 1, 40] using decide
  trivial

def malformedContext : Context :=
  let event := { (amountContext 40).request with inputJson := "{}" }
  ⟨event, Json.mkObj [], Json.mkObj [], [event, pastSpend]⟩

-- Passing the quota alone does not bypass the existing error gate for malformed arguments.
theorem malformed_denied : (decidePolicy budget malformedContext).allow = false := by decide

#guard (decidePolicy budget malformedContext).errors.isEmpty = false
#guard_explain budget malformedContext

-- Default deny and forbid also remain part of the full admission predicate.
theorem default_denied :
    (decidePolicy { budget with rules := budget.rules.tail } (amountContext 40)).allow = false := by
  decide

theorem forbid_denied :
    (decidePolicy { budget with
      rules := forbid "freeze" ["spend"] .top "account frozen" :: budget.rules }
      (amountContext 40)).allow = false := by decide

#print axioms budget_repair
#print axioms budget_repair_replayed
#print axioms symbolic_budget_repair

run_cmd LeanGuard.Audit.check #[``budget_repair] #[`LeanGuard.Experimental.Examples]

end LeanGuard.Experimental.Examples
