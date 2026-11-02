import LeanGuard.Policy
import LeanGuard.A2A

namespace LeanGuard
open Lean Data

def optionalEventString (j : Json) (key : String) : Except String String :=
  match j.getObjVal? key with
  | .error _ => .ok ""
  | .ok value => value.getStr?

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
    actor := ← optionalEventString j "actor"
    workflow := ← optionalEventString j "workflow"
    delegation := ← optionalEventString j "delegation"
    peer := ← optionalEventString j "peer"
  }

structure Runtime where
  domain : String := ""
  history : History := []
  version : Nat := 0
  agents : MultiAgent.State := {}

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
  if d.actor != e.actor || d.workflow != e.workflow || d.delegation != e.delegation ||
      d.peer != e.peer then throw "outcome does not match delegation"
  if s.history.any (fun old ↦ old.id == e.id &&
      ["success", "failure", "unknown", "reconciled"].contains old.kind) then throw "duplicate outcome"
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
    let decision := decidePolicy pack ctx
    let decision := if e.delegation.isEmpty then decision else
      { decision with allow := false, errors := decision.errors ++
        ["multi-agent authority requires native journal replay"] }
    return (s, Json.mkObj [("version", toJson s.version),
      ("decision", toJson decision), ("rules", Json.mkObj values)])
  validateEvent s e
  if op == "agents_enable" then
    if s.agents.enabled || !s.history.isEmpty then throw "enable agents before recording events"
    let next := { s with
      agents := { enabled := true }
      history := e :: s.history
      version := s.version + 1 }
    return (next, Json.mkObj [("version", toJson next.version)])
  if op == "agents_grant" then
    let grant : MultiAgent.Grant ← fromJson? (← field input "grant")
    if grant.principal != e.principal then throw "grant principal mismatch"
    let agents ← MultiAgent.issue s.agents grant (← str input "issuer") e.time
    let e := { e with
      kind := "agent_grant", resource := grant.id, actor := grant.actor,
      workflow := grant.workflow, delegation := grant.id, binding := grant.parent,
      outputJson := (toJson grant).compress }
    let next := { s with agents := agents, history := e :: s.history, version := s.version + 1 }
    return (next, Json.mkObj [("version", toJson next.version)])
  if op == "agents_revoke" then
    let id ← str input "delegation"
    let g ← s.agents.grant id
    if g.principal != e.principal then throw "grant principal mismatch"
    let e := { e with
      kind := "agent_revoke", resource := id, actor := g.actor,
      workflow := g.workflow, delegation := id }
    let next := { s with
      agents := { s.agents with revoked := id :: s.agents.revoked },
      history := e :: s.history, version := s.version + 1 }
    return (next, Json.mkObj [("version", toJson next.version)])
  if op == "agents_status" then
    return (s, Json.mkObj [("version", toJson s.version), ("agents", toJson s.agents)])
  if ["agents_update", "agents_stream_error", "agents_reconcile"].contains op then
    let some dispatch := s.history.find? (fun d ↦ d.id == e.id && d.kind == "dispatch")
      | throw "task update without dispatch"
    if !A2A.transportActions.contains dispatch.action then throw "not an A2A dispatch"
    if dispatch.principal != e.principal || dispatch.actor != e.actor ||
        dispatch.delegation != e.delegation || dispatch.peer != e.peer ||
        dispatch.workflow != e.workflow || dispatch.session != e.session ||
        dispatch.action != e.action || dispatch.resource != e.resource ||
        dispatch.inputJson != e.inputJson || dispatch.binding != e.binding ||
        dispatch.amount != e.amount then
      throw "task update does not match dispatch"
    if op == "agents_reconcile" && s.history.any (fun old ↦ old.id == e.id &&
        ["success", "failure", "reconciled"].contains old.kind) then
      throw "operation already settled"
    let output ← field input "outcome"
    let agents ← if op == "agents_stream_error" then pure s.agents
      else A2A.updateTask s.agents dispatch output
    let update := { dispatch with
      kind := if op == "agents_reconcile" then "reconciled"
        else if op == "agents_update" then "task_update" else "stream_error", time := e.time,
      outputJson := output.compress }
    let next := { s with agents := agents, history := update :: s.history, version := s.version + 1 }
    return (next, Json.mkObj [("version", toJson next.version)])
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
    let pack ← resolve s.domain
    let policy := decidePolicy pack context
    let authority := if s.agents.enabled then do
      let chain ← MultiAgent.authorize s.agents e
      A2A.taskAccess s.agents e arguments
      pure chain
      else if e.delegation.isEmpty && e.actor.isEmpty && e.workflow.isEmpty && e.peer.isEmpty then
        .ok [] else .error "multi-agent mode is not enabled"
    let decision := if s.agents.enabled then
      MultiAgent.decideAdmission pack context authority
      else MultiAgent.restrict policy authority
    let agents := if decision.allow then
      MultiAgent.charge s.agents (authority.toOption.getD []) e.amount else s.agents
    let next := { s with
      history := reserve decision.allow e context.history
      agents := agents
      version := s.version + 1 }
    return (next, Json.mkObj [("decision", toJson decision), ("version", toJson next.version)])
  throw s!"unknown operation: {op}"

end LeanGuard
