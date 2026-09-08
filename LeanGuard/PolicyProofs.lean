import LeanGuard.Policy
import LeanGuard.TemporalProofs

namespace LeanGuard

/-- The runtime decision is both sound and complete for its LeanLTL policy meaning. -/
theorem decision_leanLTL_correct (pack : PolicyPack) (ctx : Context) :
    (decidePolicy pack ctx).allow = true ↔
      (historyTrace ctx.history ⊨ pack.toLeanLTL ctx) := by
  simp only [decidePolicy, Bool.and_eq_true, List.isEmpty_iff, authorize_leanLTL_correct]
  rfl

theorem decision_requirement_leanLTL (pack : PolicyPack) (ctx : Context)
    (r : Policy) (mem : r ∈ pack.rules) (scope : r.applies ctx.request.action = true)
    (effect : r.effect = .require) (allowed : (decidePolicy pack ctx).allow = true) :
    historyTrace ctx.history ⊨ r.condition.toLeanLTL (atomValue ctx) :=
  authorized_requirement_leanLTL pack.rules _ _ _ r mem scope effect
    (decision_sound pack ctx allowed)

theorem decision_no_forbid_leanLTL (pack : PolicyPack) (ctx : Context)
    (r : Policy) (mem : r ∈ pack.rules) (scope : r.applies ctx.request.action = true)
    (effect : r.effect = .forbid) (allowed : (decidePolicy pack ctx).allow = true) :
    ¬ (historyTrace ctx.history ⊨ r.condition.toLeanLTL (atomValue ctx)) :=
  authorized_no_forbid_leanLTL pack.rules _ _ _ r mem scope effect
    (decision_sound pack ctx allowed)

end LeanGuard
