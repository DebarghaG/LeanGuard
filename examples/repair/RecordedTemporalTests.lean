import LeanGuard.Experimental.RecordedTemporalRepair
import LeanGuard.Audit

namespace LeanGuard.Experimental.RecordedTemporalTests
open Lean

def task : DocumentTask := ⟨"session", "document", "requested", ["document"], "approval"⟩

def written (value : String) : Event := {
  id := "written", time := 1000, kind := "success", action := "write",
  principal := "sandbox-user", session := task.session, resource := task.target,
  binding := task.approvedBinding,
  inputJson := documentWriteInput task.target value
}

theorem empty_history_is_not_completion : documentCompleted task [] = false := by decide

theorem latest_write_wins :
    documentCompleted task [written "other", written "requested"] = false ∧
    documentCompleted task [written "requested", written "other"] = true := by decide +kernel

theorem malformed_completion_is_rejected :
    documentCompleted task [{ written "requested" with inputJson := "{}" }] = false ∧
    documentCompleted task [{ written "requested" with inputJson := "not JSON" }] = false := by
  decide

theorem foreign_completion_is_rejected :
    documentCompleted task [{ written "requested" with session := "other" }] = false ∧
    documentCompleted task [{ written "requested" with principal := "other" }] = false ∧
    documentCompleted task [{ written "requested" with resource := "other" }] = false := by decide

theorem denied_or_failed_write_does_not_replace_success :
    documentCompleted task
      [{ written "other" with kind := "request" }, written "requested"] = true ∧
    documentCompleted task
      [{ written "other" with kind := "failure" }, written "requested"] = true := by
  decide +kernel

def completedPast : History := [written "requested"]

theorem stop_when_complete : ∃ calls : List DocumentCall, calls = [] ∧
    documentPlanLTL task completedPast calls 1 (documentCompleted task completedPast) = true := by
  guard_repair? [[]] using decide +kernel

theorem cannot_stop_when_incomplete :
    documentPlanLTL task [] [] 0 (documentCompleted task []) = false := by decide

#print axioms stop_when_complete
run_cmd do
  LeanGuard.Audit.check #[``stop_when_complete, ``documentPlanSafe_eq_leanLTL,
    ``lookupRepair_iff_leanLTL] #[`LeanGuard.Experimental.RecordedTemporalTests]

end LeanGuard.Experimental.RecordedTemporalTests
