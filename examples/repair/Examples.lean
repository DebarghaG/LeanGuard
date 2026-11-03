import LeanGuard.Experimental.Repair
import LeanGuard.Examples
import LeanGuard.Audit

/-!
# Repair experiments against native LeanGuard decisions

Build `LeanGuard.Experimental.Repair`, then run
`lake env lean examples/repair/Examples.lean`. All contexts here are hand-built.
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

/-- The test context with a different amount. History and facts are unchanged. -/
def amountContext (amount : Nat) : Context :=
  let arguments := Json.mkObj [("amount", toJson amount)]
  let event := { request with amount := amount, inputJson := arguments.compress }
  ⟨event, arguments, Json.mkObj [], [event, pastSpend]⟩

theorem original_denied : (decidePolicy budget (amountContext 70)).allow = false := by decide

#guard_explain budget (amountContext 70)

-- 70 and 50 exceed the budget and 0 isn't positive, so 40 wins. The goal also says the
-- amount may only go down.
theorem budget_repair : ∃ amount : Nat, 0 < amount ∧ amount ≤ 70 ∧
    (decidePolicy budget (amountContext amount)).allow = true := by
  guard_repair? [70, 50, 0, 40]

-- The same witness, proved without the tactic.
theorem budget_repair_replayed : ∃ amount : Nat, 0 < amount ∧ amount ≤ 70 ∧
    (decidePolicy budget (amountContext amount)).allow = true := by
  exact ⟨40, by decide⟩

-- Candidates can be symbolic expressions, proved from hypotheses.
theorem symbolic_budget_repair (spent cap proposed : Nat)
    (available : spent ≤ cap) (oversized : cap ≤ spent + proposed) :
    ∃ amount : Nat, amount ≤ proposed ∧ spent + amount = cap := by
  guard_repair? [proposed, cap - spent] using omega

-- When search fails, the goal is left untouched for the next tactic.
theorem failed_search_restores_goal : ∃ amount : Nat, amount = 40 := by
  fail_if_success guard_repair? [70, 50]
  exact ⟨40, rfl⟩

-- A candidate proved with `sorry` doesn't count.
set_option linter.unreachableTactic false in
theorem unproved_candidate_rejected : ∃ amount : Nat, amount = 40 := by
  fail_if_success guard_repair? [40] using skip
  fail_if_success guard_repair? [40] using sorry
  exact ⟨40, rfl⟩

-- Only the main goal is closed; other open goals remain.
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

-- A direct proof that no amount works in this context.
theorem write_amount_cannot_repair (amount : Nat) :
    (decidePolicy LeanGuard.Examples.documents (writeAmountContext amount)).allow = false := by
  rfl

-- So the search has to fail too.
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

-- Malformed arguments are still denied even when the quota passes.
theorem malformed_denied : (decidePolicy budget malformedContext).allow = false := by decide

#guard (decidePolicy budget malformedContext).errors.isEmpty = false
#guard_explain budget malformedContext

-- Default deny and forbid rules still apply.
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
