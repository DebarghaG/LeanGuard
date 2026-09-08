import LeanGuardAudit
import LeanGuard.Domains.Airline
import LeanGuard.Query

#print axioms LeanGuard.evaluate_correct
#print axioms LeanGuard.authorized_requirement
#print axioms LeanGuard.authorized_no_forbid
#print axioms LeanGuard.external_cannot_override
#print axioms LeanGuard.replay_history
#print axioms LeanGuard.quota_reservation_bound
#print axioms LeanGuard.confirmation_not_consumed
#print axioms LeanGuard.confirmation_has_witness
#print axioms LeanGuard.decision_sound
#print axioms LeanGuard.native_trace_safe
#print axioms LeanGuard.Domains.Airline.cancellation_correct
#print axioms LeanGuard.confirmedWithin_preserves
#print axioms LeanGuard.confirmedWithin_recent_witness
#print axioms LeanGuard.query_membership
#print axioms LeanGuard.query_window
#print axioms LeanGuard.distinct_membership
#print axioms LeanGuard.distinct_duplicate
#print axioms LeanGuard.historyTrace_shift
#print axioms LeanGuard.inWindow_correct
#print axioms LeanGuard.holds_iff_leanLTL
#print axioms LeanGuard.evaluate_leanLTL_correct
#print axioms LeanGuard.evaluate_eq_decide_leanLTL
#print axioms LeanGuard.evaluate_of_leanLTL_imp
#print axioms LeanGuard.evaluate_eq_of_leanLTL_eq
#print axioms LeanGuard.authorize_leanLTL_correct
#print axioms LeanGuard.authorized_permit_leanLTL
#print axioms LeanGuard.authorized_requirement_leanLTL
#print axioms LeanGuard.authorized_no_forbid_leanLTL
#print axioms LeanGuard.decision_leanLTL_correct
#print axioms LeanGuard.decision_requirement_leanLTL
#print axioms LeanGuard.decision_no_forbid_leanLTL
#print axioms LeanGuard.native_trace_leanLTL_safe
#print axioms LeanGuard.replay_leanLTL_correct
#print axioms LeanGuard.confirmation_leanLTL_witness
#print axioms LeanGuard.confirmation_leanLTL_unconsumed
#print axioms LeanGuard.confirmedWithin_leanLTL_recent_witness
#print axioms LeanGuard.query_leanLTL_membership
#print axioms LeanGuard.toLeanLTL_once_disj
#print axioms LeanGuard.evaluate_once_disj
