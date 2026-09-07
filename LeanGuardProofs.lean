import LeanGuard.Policy
import LeanGuard.Reservations
import LeanLTL.TraceSet.Basic

/-!
# Trace safety of native decisions

The theorem quantifies over arbitrary finite or infinite traces of decision contexts.
It uses the actual runtime decision function. Contexts contain their histories rather
than a caller-asserted `approved` bit. Replay and the host's durable protocol establish
the connection to external event streams; authenticity and complete interception are
explicit deployment assumptions, not axioms introduced into Lean.
-/

namespace LeanGuard

def SafeDecision (pack : PolicyPack) (ctx : Context) : Prop :=
  (decidePolicy pack ctx).allow = true →
    (∀ r ∈ pack.rules, r.applies ctx.request.action = true → r.effect = .require →
      Holds (atomValue ctx) r.condition ctx.history) ∧
    (∀ r ∈ pack.rules, r.applies ctx.request.action = true → r.effect = .forbid →
      ¬ Holds (atomValue ctx) r.condition ctx.history)

theorem native_decision_safe (pack : PolicyPack) (ctx : Context) : SafeDecision pack ctx := by
  intro allowed
  have native := decision_sound pack ctx allowed
  constructor
  · intro r mem scope effect
    exact authorized_requirement pack.rules _ _ _ r mem scope effect native
  · intro r mem scope effect
    exact authorized_no_forbid pack.rules _ _ _ r mem scope effect native

/-- Every point in an arbitrary LeanLTL trace satisfies the native admission policy. -/
theorem native_trace_safe (pack : PolicyPack) (t : LeanLTL.Trace Context) :
    t ⊨ (LeanLTL.TraceSet.of (SafeDecision pack)).globally := by
  intro violation
  obtain ⟨n, _, hn, bad⟩ := violation
  exact bad (native_decision_safe pack _)

end LeanGuard
