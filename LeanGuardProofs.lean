import LeanGuard.PolicyProofs
import LeanGuard.QueryProofs
import LeanGuard.Reservations
import LeanLTL.TraceSet.Basic

/-!
# Trace safety of native decisions

These theorems are about any finite or infinite trace of decision contexts, using the
same decision function the server runs. Each context carries its own history, so
approval is a past event the policy can check rather than a flag. Whether those
histories match what really happened is up to the host; see `docs/guarantees.md`.
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

/-- `SafeDecision` holds at every point of any trace of decision contexts. -/
theorem native_trace_safe (pack : PolicyPack) (t : LeanLTL.Trace Context) :
    t ⊨ (LeanLTL.TraceSet.of (SafeDecision pack)).globally := by
  intro violation
  obtain ⟨n, _, hn, bad⟩ := violation
  exact bad (native_decision_safe pack _)

/-- If the call is allowed, its history satisfies the pack's full LeanLTL meaning, error gate included. -/
def LeanLTLSafeDecision (pack : PolicyPack) (ctx : Context) : Prop :=
  (decidePolicy pack ctx).allow = true →
    (historyTrace ctx.history ⊨ pack.toLeanLTL ctx)

theorem native_decision_leanLTL_safe (pack : PolicyPack) (ctx : Context) :
    LeanLTLSafeDecision pack ctx := (decision_leanLTL_correct pack ctx).mp

/-- `LeanLTLSafeDecision` holds at every point of any trace of decision contexts. -/
theorem native_trace_leanLTL_safe (pack : PolicyPack) (t : LeanLTL.Trace Context) :
    t ⊨ (LeanLTL.TraceSet.of (LeanLTLSafeDecision pack)).globally := by
  rw [LeanLTL.TraceSet.globally_eq_globally, LeanLTL.TraceSet.sat_globally_iff]
  intro i hi
  exact native_decision_leanLTL_safe pack _

end LeanGuard
