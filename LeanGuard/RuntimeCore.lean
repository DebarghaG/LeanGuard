import LeanGuard.Policy

namespace LeanGuard
open Lean Data

def eventFromJson (j : Json) : Except String Event := do
  return {
    id := ← str j "id"
    time := ← nat j "time"
    kind := ← str j "kind"
    principal := ← str j "principal"
    session := ← str j "session"
    action := ← str j "action"
    resource := ← str j "resource"
    binding := ← str j "binding"
    amount := ← nat j "amount"
    inputJson := ((j.getObjVal? "input").toOption.getD (Json.mkObj [])).compress
    outputJson := ((j.getObjVal? "output").toOption.getD .null).compress
    factsJson := ((j.getObjVal? "facts").toOption.getD (Json.mkObj [])).compress
  }

structure Runtime where
  domain : String := ""
  history : History := []
  version : Nat := 0

def manifest (pack : PolicyPack) : Json :=
  Json.mkObj [
    ("domain", toJson pack.name),
    ("protocol", toJson (1 : Nat)),
    ("schemas", Json.mkObj pack.schemas),
    ("schema_max_depth", toJson (64 : Nat)),
    ("rules", toJson (pack.rules.map fun r ↦ Json.mkObj [
      ("id", toJson r.id), ("effect", toJson (reprStr r.effect)),
      ("actions", toJson r.actions), ("source", toJson r.source),
      ("checks", toJson (r.condition.atoms.map Check.name))
    ]))
  ]

def validateEvent (s : Runtime) (e : Event) : Except String Unit := do
  if e.id.isEmpty || e.principal.isEmpty || e.session.isEmpty then throw "empty identity"
  if s.history.head?.any (fun previous ↦ e.time < previous.time) then
    throw "time moved backwards"

def validateOutcome (s : Runtime) (e : Event) : Except String Event := do
  let dispatches := s.history.filter fun d ↦ d.id == e.id && d.kind == "dispatch"
  let some d := dispatches.head? | throw "outcome without dispatch"
  if d.principal != e.principal || d.session != e.session || d.action != e.action ||
      d.resource != e.resource || d.binding != e.binding || d.inputJson != e.inputJson ||
      d.amount != e.amount then
    throw "outcome does not match dispatch"
  if s.history.any (fun old ↦ old.id == e.id &&
      ["success", "failure", "unknown"].contains old.kind) then throw "duplicate outcome"
  return d

def handleWith (resolve : String → Except String PolicyPack) (s : Runtime) (input : Json) : Except String (Runtime × Json) := do
  if (← nat input "protocol") != 1 then throw "unsupported protocol version"
  let op ← str input "op"
  if op == "load" then
    if s.domain != "" then throw "policy pack is immutable after load"
    let domain ← str input "domain"
    let pack ← resolve domain
    validatePack pack
    return ({ s with domain := domain }, Json.mkObj [("manifest", manifest pack),
      ("version", toJson s.version)])
  if s.domain == "" then throw "load a policy pack first"
  if (← nat input "version") != s.version then throw "stale monitor version"
  if op == "status" then
    return (s, Json.mkObj [("version", toJson s.version), ("events", toJson s.history.length)])
  let e ← eventFromJson (← field input "event")
  if op == "audit" then
    let events ← (← Data.array input "history").toList.mapM eventFromJson
    let arguments ← field input "arguments"
    let facts ← field input "facts"
    let e := { e with
      inputJson := arguments.compress
      outputJson := "null"
      factsJson := facts.compress }
    let ctx : Context := ⟨e, arguments, facts, e :: events⟩
    let pack ← resolve s.domain
    let values := (pack.rules.filter (fun r ↦ r.applies e.action)).map fun r ↦
      (r.id, toJson (evaluate (atomValue ctx) r.condition ctx.history))
    return (s, Json.mkObj [("version", toJson s.version),
      ("decision", toJson (decidePolicy pack ctx)), ("rules", Json.mkObj values)])
  validateEvent s e
  if op == "observe" then
    let e := match input.getObjVal? "outcome" with
      | .ok output => { e with outputJson := output.compress }
      | .error _ => e
    let e ← if ["success", "failure", "unknown"].contains e.kind then do
      let dispatch ← validateOutcome s e
      pure { e with factsJson := dispatch.factsJson }
    else do
      if !["confirmed", "revoked", "identity", "compensation_requested", "travelling",
          "user_action", "user_observation"].contains e.kind then throw "untrusted event kind"
      if s.history.any (fun old ↦ old.id == e.id) then throw "duplicate event id"
      pure { e with factsJson := "{}" }
    let next := { s with history := e :: s.history, version := s.version + 1 }
    return (next, Json.mkObj [("version", toJson next.version)])
  if op == "admit" then
    let arguments ← field input "arguments"
    let facts ← field input "facts"
    let e := { e with
      inputJson := arguments.compress
      outputJson := "null"
      factsJson := facts.compress }
    if e.kind != "request" then throw "admission needs a request event"
    if s.history.any (fun old ↦ old.id == e.id) then throw "duplicate request id"
    let context : Context := {
      request := e, arguments := arguments, facts := facts,
      history := e :: s.history
    }
    let decision := decidePolicy (← resolve s.domain) context
    let next := { s with
      history := reserve decision.allow e context.history
      version := s.version + 1 }
    return (next, Json.mkObj [("decision", toJson decision), ("version", toJson next.version)])
  throw s!"unknown operation: {op}"

end LeanGuard
