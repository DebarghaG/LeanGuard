import LeanGuard.Tests
import LeanGuard.PolicyProofs

/-! Kernel-checked regressions stated directly as LeanLTL satisfaction propositions. -/

namespace LeanGuard.TemporalTests
open Tests

theorem empty_previous :
    ¬ (historyTrace [] ⊨ (Formula.previous none (.top : Formula String)).toLeanLTL atom) := by
  decide

theorem empty_once :
    ¬ (historyTrace [] ⊨ (Formula.once none (.top : Formula String)).toLeanLTL atom) := by
  decide

theorem empty_since :
    ¬ (historyTrace [] ⊨ (Formula.since none .top (.top : Formula String)).toLeanLTL atom) := by
  decide

theorem empty_negation :
    historyTrace [] ⊨ (Formula.neg (.bot : Formula String)).toLeanLTL atom := by
  decide

theorem singleton_strong_previous :
    ¬ (historyTrace [event "now" 100] ⊨
      (Formula.previous none (Formula.neg (.atom "absent"))).toLeanLTL atom) := by
  decide

theorem inclusive_window :
    historyTrace trace ⊨ (Formula.once (some 10) (.atom "approval")).toLeanLTL atom := by
  decide

theorem expired_window :
    ¬ (historyTrace trace ⊨ (Formula.once (some 10) (.atom "old")).toLeanLTL atom) := by
  decide

theorem unbounded_excludes_future :
    ¬ (historyTrace [event "now" 90, event "future" 100] ⊨
      (Formula.once none (.atom "future")).toLeanLTL atom) := by
  decide

theorem zero_window_equal_times :
    historyTrace [event "now" 100, event "approval" 100] ⊨
      (Formula.previous (some 0) (.atom "approval")).toLeanLTL atom := by
  decide

theorem since_immediate_witness :
    historyTrace [event "approval" 100] ⊨
      (Formula.since none .bot (.atom "approval")).toLeanLTL atom := by
  decide

theorem since_excludes_witness_from_left :
    historyTrace trace ⊨
      (Formula.since none (.neg (.atom "approval")) (.atom "approval")).toLeanLTL atom := by
  decide

theorem since_checks_intervening_positions :
    ¬ (historyTrace [event "now" 100, event "revoked" 95, event "approval" 90] ⊨
      (Formula.since none (.neg (.atom "revoked")) (.atom "approval")).toLeanLTL atom) := by
  decide

theorem nested_window_origin :
    historyTrace [event "now" 100, event "previous" 90, event "old" 80] ⊨
      (Formula.previous none (.once (some 10) (.atom "old"))).toLeanLTL atom := by
  decide

theorem scope_before_previous :
    historyTrace [event "now" 100, { event "foreign" 95 with session := "other" },
      event "approval" 90] ⊨
      (Formula.within .conversation (.previous none (.atom "approval"))).toLeanLTL atom := by
  decide

theorem suffix_sensitive_atom :
    historyTrace trace ⊨ (Formula.once none (.atom ())).toLeanLTL
      (fun _ h ↦ h.length == 2) := by
  decide

theorem bounded_confirmation :
    historyTrace (timedApproval 3600).history ⊨
      (confirmedWithin 3600).toLeanLTL (atomValue (timedApproval 3600)) := by
  decide

theorem expiry_uses_decision_clock :
    ¬ (historyTrace shiftedApproval.history ⊨
      (confirmedWithin 3600).toLeanLTL (atomValue shiftedApproval)) := by
  decide

theorem errors_prevent_leanLTL_admission :
    ¬ (historyTrace errorContext.history ⊨ errorPack.toLeanLTL errorContext) := by
  intro accepted
  have allowed := (decision_leanLTL_correct errorPack errorContext).mpr accepted
  have denied : (decidePolicy errorPack errorContext).allow = false := by decide
  rw [denied] at allowed
  contradiction

end LeanGuard.TemporalTests
