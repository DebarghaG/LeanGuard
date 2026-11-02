import LeanGuard.MultiAgent

/-! A2A wire normalization and protocol-specific policies. Authority and task phases
remain protocol-independent in MultiAgent; no remote payload can issue a grant. -/
namespace LeanGuard.A2A
open Lean Data MultiAgent

def phaseFromWire : String → Except String TaskPhase
  | "TASK_STATE_SUBMITTED" => .ok .submitted
  | "TASK_STATE_WORKING" => .ok .working
  | "TASK_STATE_INPUT_REQUIRED" => .ok .inputRequired
  | "TASK_STATE_AUTH_REQUIRED" => .ok .authRequired
  | "TASK_STATE_COMPLETED" => .ok .completed
  | "TASK_STATE_CANCELED" => .ok .canceled
  | "TASK_STATE_REJECTED" => .ok .rejected
  | "TASK_STATE_FAILED" => .ok .failed
  | _ => .error "invalid A2A task state"

def transportActions := ["a2a.send", "a2a.get", "a2a.cancel", "a2a.subscribe"]

def optionalString (j : Json) (key : String) : Except String String :=
  match j.getObjVal? key with
  | .error _ => .ok ""
  | .ok value => value.getStr?

def taskAccess (s : State) (e : Event) (args : Json) : Except String Unit := do
  if !transportActions.contains e.action then return
  if (← str args "peer") != e.peer then throw "peer does not match interaction"
  let id ← str args "task_id"
  let context ← str args "context_id"
  let payload ← field args "payload"
  if e.action == "a2a.send" then
    let message ← field payload "message"
    if (← str message "role") != "ROLE_USER" || (← str message "messageId").isEmpty then
      throw "invalid A2A user message"
    let _ ← array message "parts"
    if (← optionalString message "taskId") != id ||
        (← optionalString message "contextId") != context then throw "message scope mismatch"
  else if (← str payload "id") != id then throw "payload task mismatch"
  if id.isEmpty then
    if e.action != "a2a.send" then throw "task identifier required"
    -- A context alone cannot establish ownership of an existing conversation.
    if !context.isEmpty && !(s.contexts.any fun t ↦ t.peer == e.peer &&
        t.id == context && t.principal == e.principal && t.actor == e.actor &&
        t.workflow == e.workflow && t.delegation == e.delegation && t.resource == e.resource) then
      throw "unknown or inaccessible context"
    return
  let some t := s.tasks.find? (fun t ↦ t.peer == e.peer && t.id == id)
    | throw "unknown or inaccessible task"
  if t.principal != e.principal || t.actor != e.actor || t.workflow != e.workflow ||
      t.delegation != e.delegation || t.resource != e.resource then
    throw "unknown or inaccessible task"
  if !context.isEmpty && context != t.context then throw "task/context mismatch"
  if ["a2a.send", "a2a.subscribe"].contains e.action && t.state.terminal then
    throw "task is terminal"

def taskTerminalEvent : Formula Check := check "remote_task_terminal" fun c ↦ do
  let id ← str c.arguments "task_id"
  let some e := c.history.head? | return false
  if !["task_update", "reconciled"].contains e.kind || e.peer != c.request.peer ||
      !samePrincipal c.request e then
    return false
  let output ← Json.parse e.outputJson
  let payload := (output.getObjVal? "task").toOption
  let update := (output.getObjVal? "statusUpdate").toOption
  let some value := payload.or update | return false
  if (← str value (if payload.isSome then "id" else "taskId")) != id then return false
  return (← phaseFromWire (← str (← field value "status") "state")).terminal

def taskOpen : Formula Check := .disj
  (check "new_task" fun c ↦ do return (← str c.arguments "task_id").isEmpty)
  (.neg (.once none taskTerminalEvent))

def noUnresolvedSend : Formula Check := check "no_unresolved_peer_send" fun c ↦ .ok (
  !(c.history.any fun e ↦ sameResource c.request e && e.peer == c.request.peer &&
    e.action == "a2a.send" && e.kind == "dispatch" &&
    !(c.history.any fun outcome ↦ outcome.id == e.id &&
      ["success", "failure", "reconciled"].contains outcome.kind)))

def noMessageReplay : Formula Check := check "unique_peer_message" fun c ↦ do
  let message ← str (← field (← field c.arguments "payload") "message") "messageId"
  return !(c.history.any fun e ↦ samePrincipal c.request e && e.peer == c.request.peer &&
    e.kind == "dispatch" && e.action == "a2a.send" &&
    ((Json.parse e.inputJson).bind fun args ↦ do
      str (← field (← field args "payload") "message") "messageId").toOption == some message)

/-- Updates are evidence about an already admitted operation, never new authority.
Poll snapshots may skip intermediate states. A terminal task cannot be restarted. -/
def updateTask (s : State) (e : Event) (output : Json) : Except String State := do
  let task := (output.getObjVal? "task").toOption
  let status := (output.getObjVal? "statusUpdate").toOption
  let artifact := (output.getObjVal? "artifactUpdate").toOption
  let message := (output.getObjVal? "message").toOption
  let values := [task, status, artifact, message].filterMap id
  if values.length != 1 then throw "expected one task update payload"
  let some payload := values.head? | throw "missing task update"
  let args ← Json.parse e.inputJson
  let requested ← str args "task_id"
  if message.isSome && (!requested.isEmpty || e.action != "a2a.send") then
    throw "task interaction returned a stateless message"
  if message.isSome then
    if (← str payload "role") != "ROLE_AGENT" || (← str payload "messageId").isEmpty then
      throw "invalid A2A response message"
    let _ ← array payload "parts"
  let context ← if message.isSome && !(payload.getObjVal? "contextId").isOk then pure ""
    else str payload "contextId"
  let requestedContext ← str args "context_id"
  if !requestedContext.isEmpty && requestedContext != context then throw "response context mismatch"
  let id ← if message.isSome then pure "" else str payload (if task.isSome then "id" else "taskId")
  if !message.isSome && (id.isEmpty || context.isEmpty) then throw "empty remote task identity"
  if !requested.isEmpty && requested != id then throw "response task mismatch"
  let target := if message.isSome then ResponseTarget.message context else .task id context
  let mut s ← s.bindResponse e.id target
  if !context.isEmpty then
    if let some owner := s.contexts.find? (fun c ↦ c.peer == e.peer && c.id == context) then
      if owner.principal != e.principal || owner.actor != e.actor ||
          owner.workflow != e.workflow || owner.delegation != e.delegation ||
          owner.resource != e.resource then throw "response context ownership mismatch"
    else
      s := { s with contexts := ⟨e.principal, e.actor, e.workflow, e.delegation,
        e.peer, context, e.resource⟩ :: s.contexts }
  if message.isSome then return s
  let old := s.tasks.find? (fun t ↦ t.peer == e.peer && t.id == id)
  if let some t := old then
    if t.principal != e.principal || t.actor != e.actor || t.workflow != e.workflow ||
        t.delegation != e.delegation || t.resource != e.resource || t.context != context then
      throw "response task ownership mismatch"
  else if task.isNone || e.action != "a2a.send" then throw "update without a known task"
  if artifact.isSome then
    if old.any (fun t ↦ t.state.terminal) then throw "artifact update after task termination"
    return s
  let state ← phaseFromWire (← str (← field payload "status") "state")
  if old.any (fun t ↦ !taskTransition t.state state) then throw "terminal task changed state"
  let next : Task := ⟨e.principal, e.actor, e.workflow, e.delegation, e.peer, id, context,
    e.resource, state⟩
  return { s with tasks := next :: s.tasks.filter (fun t ↦ !(t.peer == e.peer && t.id == id)) }

def withOperations (pack : PolicyPack) : PolicyPack := withSchemas
  { pack with rules := pack.rules ++ [permit "agents.transport" transportActions,
    require "agents.scoped" transportActions (check "delegated_peer" fun c ↦
      .ok (!c.request.delegation.isEmpty && !c.request.actor.isEmpty &&
        !c.request.workflow.isEmpty && !c.request.peer.isEmpty)) "bound actor, workflow and peer",
    require "agents.task_open" ["a2a.send", "a2a.subscribe"] taskOpen "terminal tasks cannot restart",
    require "agents.no_unresolved_send" ["a2a.send"] noUnresolvedSend
      "reconcile an uncertain send before dispatching again to this peer/resource",
    require "agents.message_replay" ["a2a.send"] noMessageReplay
      "one dispatch per peer/message identifier"] }
  (transportActions.map fun action ↦ (action, .object ["peer", "task_id", "context_id", "payload"]
    [("peer", .string), ("task_id", .string), ("context_id", .string), ("payload", .object [] [])]))

end LeanGuard.A2A
