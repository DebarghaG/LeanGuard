import LeanGuard.Experimental.RecordedRepair
import LeanGuard.Experimental.TemporalRepair

/-! LeanLTL admission checks for the existing saved-rollout repair contracts. -/

namespace LeanGuard.Experimental
open Lean

def acceptedLeanLTL (domain : String) (ctx : Context) : Prop :=
  match packFor domain with
  | .ok pack => historyTrace ctx.history ⊨ pack.toLeanLTL ctx
  | .error _ => False

theorem accepted_iff_leanLTL (domain : String) (ctx : Context) :
    accepted domain ctx = true ↔ acceptedLeanLTL domain ctx := by
  unfold accepted acceptedLeanLTL
  cases packFor domain with
  | ok pack => exact decision_leanLTL_correct pack ctx
  | error _ => simp

instance (domain : String) (ctx : Context) : Decidable (acceptedLeanLTL domain ctx) :=
  decidable_of_iff (accepted domain ctx = true) (accepted_iff_leanLTL domain ctx)

theorem accepted_eq_decide_leanLTL (domain : String) (ctx : Context) :
    accepted domain ctx = decide (acceptedLeanLTL domain ctx) := by
  apply Bool.eq_iff_iff.mpr
  simp only [decide_eq_true_eq, accepted_iff_leanLTL]

def lookupRepairLTL (ctx : Context) (customer : String) : Prop :=
  (Data.str ctx.facts "customer_id").toOption = some customer ∧
    ctx.request.action = "get_user_details" ∧ acceptedLeanLTL "airline" (lookupContext ctx customer)

instance (ctx : Context) (customer : String) : Decidable (lookupRepairLTL ctx customer) :=
  inferInstanceAs (Decidable (_ ∧ _ ∧ _))

theorem lookupRepair_iff_leanLTL (ctx : Context) (customer : String) :
    lookupRepair ctx customer ↔ lookupRepairLTL ctx customer := by
  simp only [lookupRepair, lookupRepairLTL, accepted_iff_leanLTL]

/-- Run the same fixture transitions and intent checks using complete LeanLTL admission. -/
def documentPlanLTL (task : DocumentTask) (past : History)
    (calls : List DocumentCall) (index : Nat := 0) (done : Bool := false) : Bool :=
  documentPlanWith (fun ctx ↦ decide (acceptedLeanLTL "example" ctx)) task past calls index done

theorem documentPlanSafe_eq_leanLTL (task : DocumentTask) (past : History)
    (calls : List DocumentCall) (index : Nat) (done : Bool) :
    documentPlanSafe task past calls index done = documentPlanLTL task past calls index done := by
  have same : accepted "example" = fun ctx ↦ decide (acceptedLeanLTL "example" ctx) :=
    funext (accepted_eq_decide_leanLTL "example")
  simp only [documentPlanSafe, documentPlanLTL, same]

/-- Canonical encoding for the fixture's two string arguments, using Lean's total string printer. -/
def documentWriteInput (resource value : String) : String :=
  "{\"resource\":" ++ Json.renderString resource ++ ",\"value\":" ++ Json.renderString value ++ "}"

/-- Recover completion from the most recent successful target write in the trusted fixture.
A later write supersedes earlier values. Evidence must use the fixture's canonical JSON encoding
of the exact requested arguments; arbitrary external event serialization is not supported. -/
def documentCompleted (task : DocumentTask) (past : History) : Bool :=
  match past.find? (fun e ↦ e.principal == "sandbox-user" && e.session == task.session &&
      e.kind == "success" && e.action == "write" && e.resource == task.target) with
  | none => false
  | some e => e.inputJson == documentWriteInput task.target task.value

end LeanGuard.Experimental
