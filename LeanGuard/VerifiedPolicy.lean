import LeanGuard.Policy

namespace LeanGuard

/-- A policy and its explicitly stated, admission-conditional safety contract.
The contract still needs review; a vacuous specification is also provable.
Audit this declaration and its dependencies before distributing the executable. -/
structure VerifiedPolicy where
  pack : PolicyPack
  property : String
  Safe : Context → Prop
  sound : ∀ ctx, (decidePolicy pack ctx).allow = true → Safe ctx

end LeanGuard
