import LeanGuard.Experimental.Repair
import LeanGuard.PolicyProofs

/-!
# Repair goals stated in LeanLTL

The existing correspondence theorem supplies constructive decidability for a full
policy's LeanLTL meaning. This opt-in adapter lets ordinary `decide` (and therefore
`guard_repair?`) handle the policy goal without changing the policy or its semantics.
-/

namespace LeanGuard.Experimental

/-- Decide complete policy satisfaction using the already-proved runtime equivalence. -/
instance decidablePolicyLeanLTL (pack : PolicyPack) (ctx : Context) :
    Decidable (historyTrace ctx.history ⊨ pack.toLeanLTL ctx) :=
  decidable_of_iff ((decidePolicy pack ctx).allow = true) (decision_leanLTL_correct pack ctx)

/-- Repair existence is unchanged by stating compliance in LeanLTL instead of the allow bit.
The caller's edit contract is retained, for every policy, context family, and history. -/
theorem repair_iff_leanLTL (pack : PolicyPack) (context : α → Context) (permitted : α → Prop) :
    (∃ edit, permitted edit ∧ (decidePolicy pack (context edit)).allow = true) ↔
      ∃ edit, permitted edit ∧
        (historyTrace (context edit).history ⊨ pack.toLeanLTL (context edit)) := by
  simp only [decision_leanLTL_correct]

end LeanGuard.Experimental
