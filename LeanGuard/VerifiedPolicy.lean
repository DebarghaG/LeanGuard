import LeanGuard.Policy

namespace LeanGuard

/-- A pack together with a proof that every call it allows satisfies `Safe`. Read `Safe`
carefully: a weak property, or a pack that denies everything, also type-checks. -/
structure VerifiedPolicy where
  pack : PolicyPack
  property : String
  Safe : Context → Prop
  sound : ∀ ctx, (decidePolicy pack ctx).allow = true → Safe ctx

end LeanGuard
