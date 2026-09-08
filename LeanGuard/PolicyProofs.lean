import LeanGuard.Policy
import LeanGuard.TemporalProofs

namespace LeanGuard

/-- Independent error semantics: every Boolean branch, but only temporally relevant
positions. A since witness requires its right operand and all intervening left operands. -/
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
