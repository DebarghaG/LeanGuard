import LeanGuard.Policy

namespace LeanGuard
open Lean

/-- Native schema values; schemas are compiled alongside policies, never agent supplied. -/
inductive Schema where
  | any | string | integer | number | boolean | null
  | enum : List Json → Schema
  | array : Schema → Schema
  | object : List String → List (String × Schema) → Schema
  | alternatives : List Schema → Schema

def Schema.valid : Nat → Schema → Json → Bool
  | 0, _, _ => false
  | _ + 1, .any, _ => true
  | _ + 1, .string, j => j.getStr?.isOk
  | _ + 1, .integer, j => j.getInt?.isOk
  | _ + 1, .number, j => match j with | .num _ => true | _ => false
  | _ + 1, .boolean, j => j.getBool?.isOk
  | _ + 1, .null, j => j == .null
  | _ + 1, .enum values, j => values.contains j
  | fuel + 1, .array item, j =>
    match j.getArr? with
    | .ok items => items.all (item.valid fuel)
    | .error _ => false
  | fuel + 1, .object required fields, j =>
    match j with
    | .obj _ => required.all (fun key ↦ (j.getObjVal? key).isOk) &&
      fields.all (fun (key, ty) ↦ match j.getObjVal? key with
        | .ok value => ty.valid fuel value
        | .error _ => true)
    | _ => false
  | fuel + 1, .alternatives choices, j => choices.any (fun ty ↦ ty.valid fuel j)

def schemaCheck (schema : Schema) : Formula Check := check "argument_schema" fun c ↦
  if schema.valid 64 c.arguments then .ok true else .error "arguments do not match native schema"

def withSchemas (pack : PolicyPack) (schemas : List (String × Schema)) : PolicyPack :=
  { pack with rules := pack.rules ++ (schemas.map fun (action, schema) ↦
    require s!"schema.{action}" [action] (schemaCheck schema) "pinned tool input schema") }

end LeanGuard
