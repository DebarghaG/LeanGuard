import LeanGuard.Experimental.Repair
import LeanGuard.PolicyProofs

/-!
# Repair goals stated in LeanLTL

A policy's LeanLTL meaning is decidable because it agrees with the runtime decision.
This module registers that instance, so `decide`, and therefore `guard_repair?`, can
prove goals stated as LeanLTL satisfaction.
-/

namespace LeanGuard.Experimental

/-- Decides LeanLTL policy satisfaction by running the policy. -/
instance decidablePolicyLeanLTL (pack : PolicyPack) (ctx : Context) :
    Decidable (historyTrace ctx.history ⊨ pack.toLeanLTL ctx) :=
  decidable_of_iff ((decidePolicy pack ctx).allow = true) (decision_leanLTL_correct pack ctx)

/-- A repair exists for the LeanLTL goal exactly when one exists for the allow bit, with
the same edit constraint. -/
theorem repair_iff_leanLTL (pack : PolicyPack) (context : α → Context) (permitted : α → Prop) :
    (∃ edit, permitted edit ∧ (decidePolicy pack (context edit)).allow = true) ↔
      ∃ edit, permitted edit ∧
        (historyTrace (context edit).history ⊨ pack.toLeanLTL (context edit)) := by
  simp only [decision_leanLTL_correct]

end LeanGuard.Experimental
