import Lean.Meta.Tactic.Grind.RegisterCommand

/-! Registers the `guard_rule` attribute. It lives in its own module because an attribute
is only usable in files that import the module declaring it. -/

/-- Marks a lemma for `guard_solve`. Accepts the same modifiers and scoping as `@[grind]`. -/
register_grind_attr guard_rule
