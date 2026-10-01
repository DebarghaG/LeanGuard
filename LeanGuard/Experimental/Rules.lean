import Lean.Meta.Tactic.Grind.RegisterCommand

/-! A separate module makes grind's attribute registration available to importing elaborators. -/

/-- Policy lemmas for `guard_solve`, with the same modifiers and scoping as `grind`. -/
register_grind_attr guard_rule
