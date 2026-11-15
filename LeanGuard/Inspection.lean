import LeanGuard.Policy

/-! Display-only inspection of compiled policy values. No inspection field participates in admission. -/

namespace LeanGuard
open Lean

def HistoryScope.inspectionName : HistoryScope → String
  | .principal => "principal"
  | .conversation => "conversation"
  | .resource => "resource"
  | .actor => "actor"
  | .workflow => "workflow"

def Effect.inspectionName : Effect → String
  | .permit => "permit"
  | .require => "require"
  | .forbid => "forbid"

def inspectFormula : Formula Check → Json
  | .atom c => Json.mkObj [("op", toJson "atom"), ("name", toJson c.name),
      ("opaque", toJson c.inspection.isNone), ("description", c.inspection.getD .null)]
  | .top => Json.mkObj [("op", toJson "true")]
  | .bot => Json.mkObj [("op", toJson "false")]
  | .neg p => Json.mkObj [("op", toJson "not"), ("child", inspectFormula p)]
  | .conj p q => Json.mkObj [("op", toJson "and"),
      ("left", inspectFormula p), ("right", inspectFormula q)]
  | .disj p q => Json.mkObj [("op", toJson "or"),
      ("left", inspectFormula p), ("right", inspectFormula q)]
  | .previous w p => Json.mkObj [("op", toJson "previous"),
      ("window_seconds", toJson w), ("child", inspectFormula p)]
  | .once w p => Json.mkObj [("op", toJson "once"),
      ("window_seconds", toJson w), ("child", inspectFormula p)]
  | .since w p q => Json.mkObj [("op", toJson "since"), ("window_seconds", toJson w),
      ("left", inspectFormula p), ("right", inspectFormula q)]
  | .within scope p => Json.mkObj [("op", toJson "within"),
      ("scope", toJson scope.inspectionName), ("child", inspectFormula p)]

def inspectPack (pack : PolicyPack) : Json := Json.mkObj [
  ("format", toJson "leanguard.inspection"), ("version", toJson (1 : Nat)),
  ("domain", toJson pack.name), ("schemas", Json.mkObj pack.schemas),
  ("rules", toJson (pack.rules.map fun rule ↦ Json.mkObj [
    ("id", toJson rule.id), ("effect", toJson rule.effect.inspectionName),
    ("actions", toJson rule.actions), ("source", toJson rule.source),
    ("condition", inspectFormula rule.condition)])),
  ("semantics", Json.mkObj [("default", toJson "deny"), ("errors", toJson "deny"),
    ("windows", toJson "inclusive integer seconds"), ("history_order", toJson "newest first"),
    ("metadata", toJson "declared display information; not a proof of an English requirement")])]

end LeanGuard
