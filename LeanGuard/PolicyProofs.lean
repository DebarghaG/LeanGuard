import LeanGuard.Policy
import LeanGuard.TemporalProofs

namespace LeanGuard

/-- When a formula evaluates without errors, specified separately from the evaluator. Both
sides of every connective are checked, but only at positions the operator reaches. For
`since`, that is the witness and every position between it and now. -/
def ErrorFree (ctx : Context) : Formula Check → History → Prop
  | .atom a, h => ∃ value, a.run { ctx with history := h } = .ok value
  | .top, _ | .bot, _ => True
  | .neg p, h => ErrorFree ctx p h
  | .conj p q, h | .disj p q, h => ErrorFree ctx p h ∧ ErrorFree ctx q h
  | .previous w p, h => InPastWindow w h h.tail → ErrorFree ctx p h.tail
  | .once w p, h => ∀ i < h.length,
    InPastWindow w h (h.drop i) → ErrorFree ctx p (h.drop i)
  | .since w p q, h => ∀ i < h.length,
    InPastWindow w h (h.drop i) →
      ErrorFree ctx q (h.drop i) ∧ ∀ j < i, ErrorFree ctx p (h.drop j)
  | .within scope p, h => ErrorFree ctx p (projectAtHead scope h)

theorem evaluationErrors_eq_nil_iff (ctx : Context) (p : Formula Check) (h : History) :
    evaluationErrors ctx p h = [] ↔ ErrorFree ctx p h := by
  induction p generalizing h with
  | atom a => cases ha : a.run { ctx with history := h } <;>
      simp [evaluationErrors, ErrorFree, ha]
  | _ => simp_all [evaluationErrors, ErrorFree, List.flatMap_eq_nil_iff,
      List.mem_range, ← inWindow_correct]

/-- The runtime allows a call exactly when the context satisfies the pack's LeanLTL meaning. -/
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
