import LeanGuard.Temporal
import Lean.Data.Json

namespace LeanGuard
open Lean

structure Context where
  request : Event
  arguments : Json
  facts : Json
  history : History

/-- A named predicate on a context. Missing or ill-typed inputs return an error. -/
structure Check where
  name : String
  run : Context → Except String Bool
  /-- Declared display metadata. It is never consulted by the evaluator. -/
  inspection : Option Json := none

abbrev Policy := Rule Check

structure PolicyPack where
  name : String
  rules : List Policy
  schemas : List (String × Json) := []

namespace Data
def field (j : Json) (key : String) : Except String Json :=
  (j.getObjVal? key).mapError (fun e ↦ s!"{key}: {e}")

def str (j : Json) (key : String) : Except String String := do
  (← field j key).getStr?

def nat (j : Json) (key : String) : Except String Nat := do
  (← field j key).getNat?

def bool (j : Json) (key : String) : Except String Bool := do
  (← field j key).getBool?

def array (j : Json) (key : String) : Except String (Array Json) := do
  (← field j key).getArr?

def strings (j : Json) (key : String) : Except String (Array String) := do
  (← array j key).mapM Json.getStr?

def lookup (j : Json) (key : String) : Except String Json := field j key

def all (xs : Array Json) (p : Json → Except String Bool) : Except String Bool := do
  return (← xs.mapM p).all id

def any (xs : Array Json) (p : Json → Except String Bool) : Except String Bool := do
  return (← xs.mapM p).any id
end Data

def check (name : String) (run : Context → Except String Bool) : Formula Check :=
  .atom { name, run }

def require (id : String) (actions : List String) (condition : Formula Check)
    (source : String) : Policy := ⟨id, .require, actions, condition, source⟩

def permit (id : String) (actions : List String) (condition : Formula Check := .top)
    (source : String := "native policy") : Policy := ⟨id, .permit, actions, condition, source⟩

def forbid (id : String) (actions : List String) (condition : Formula Check)
    (source : String) : Policy := ⟨id, .forbid, actions, condition, source⟩

def samePrincipal (a b : Event) : Bool := a.principal == b.principal
def sameConversation (a b : Event) : Bool := samePrincipal a b && a.session == b.session
def sameResource (a b : Event) : Bool := samePrincipal a b && a.resource == b.resource

def sameAuthority (a b : Event) : Bool := a.actor == b.actor && a.workflow == b.workflow &&
  a.delegation == b.delegation && a.peer == b.peer

def eventCheck (name : String) (p : Event → Event → Bool) : Formula Check :=
  check name fun c ↦ .ok (c.history.head?.any (p c.request))

def confirmedEvent : Formula Check := .atom {
  name := "matching_confirmation"
  inspection := some (Json.mkObj [("kind", toJson "matching_confirmation")])
  run := fun c ↦ .ok (c.history.head?.any fun e ↦
    let r := c.request
    sameConversation r e && sameAuthority r e && e.kind == "confirmed" && e.action == r.action &&
      e.resource == r.resource && e.binding == r.binding && r.binding != "") }

def revokedEvent : Formula Check := .atom {
  name := "matching_revocation"
  inspection := some (Json.mkObj [("kind", toJson "matching_revocation")])
  run := fun c ↦ .ok (c.history.head?.any fun e ↦
    sameConversation c.request e && e.kind == "revoked" && e.binding == c.request.binding) }

def usedConfirmation : Formula Check := .atom {
  name := "confirmation_consumed"
  inspection := some (Json.mkObj [("kind", toJson "confirmation_consumed")])
  run := fun c ↦ .ok (c.history.head?.any fun e ↦
    sameConversation c.request e && e.kind == "dispatch" && e.binding == c.request.binding) }

/-- A matching confirmation happened earlier, hasn't been revoked, and hasn't been used by a dispatch. -/
def confirmed : Formula Check :=
  .within .conversation (.previous none ((.since none (.neg revokedEvent) confirmedEvent) ⋏
    .neg (.once none usedConfirmation)))

/-- `confirmed`, but the confirmation must be at most `seconds` old at decision time. -/
def confirmedWithin (seconds : Nat) : Formula Check :=
  confirmed ⋏ .within .conversation (.once (some seconds) confirmedEvent)

def observed (actions : List String) : Formula Check :=
  .within .conversation (.previous none (.once none
    (.atom {
      name := "successful_resource_observation"
      inspection := some (Json.mkObj [("kind", toJson "successful_resource_observation"),
        ("actions", toJson actions)])
      run := fun c ↦ .ok (c.history.head?.any fun e ↦
        let r := c.request
        sameResource r e && sameConversation r e && r.workflow == e.workflow && e.kind == "success" &&
          actions.contains e.action) })))

def neverDispatched (actions : List String) : Formula Check :=
  .neg (.once none (.atom {
    name := "resource_dispatch"
    inspection := some (Json.mkObj [("kind", toJson "resource_dispatch"), ("actions", toJson actions)])
    run := fun c ↦ .ok (c.history.head?.any fun e ↦
      sameResource c.request e && e.kind == "dispatch" && actions.contains e.action) }))

def countEvents (h : History) (p : Event → Bool) : Nat := (h.filter p).length
def sumEvents (h : History) (p : Event → Bool) : Nat :=
  (h.filter p).foldl (fun n e ↦ n + e.amount) 0

def quotaMatches (request : Event) (window : Nat) (e : Event) : Bool :=
  samePrincipal request e && e.kind == "dispatch" &&
    e.time ≤ request.time && request.time - e.time ≤ window

def quota (calls amount window : Nat) : Formula Check := .atom {
  name := "dispatch_quota"
  inspection := some (Json.mkObj [("kind", toJson "dispatch_quota"), ("calls", toJson calls),
    ("amount", toJson amount), ("window_seconds", toJson window), ("scope", toJson "principal")])
  run := fun c ↦
    let matching := quotaMatches c.request window
    .ok (countEvents c.history matching < calls &&
      sumEvents c.history matching + c.request.amount ≤ amount) }

def singleFlight : Formula Check := .atom {
  name := "single_inflight_call"
  inspection := some (Json.mkObj [("kind", toJson "single_inflight_call")])
  run := fun c ↦ .ok (!(c.history.any fun e ↦
    (sameConversation c.request e || sameResource c.request e) && e.kind == "dispatch" &&
    !(c.history.any fun outcome ↦ outcome.id == e.id &&
      (["success", "failure", "reconciled"].contains outcome.kind)))) }

structure Decision where
  allow : Bool
  reasons : List String
  errors : List String
  evidence : List String
  deriving ToJson, FromJson

def evaluationErrors (ctx : Context) : Formula Check → History → List String
  | .atom a, h => match a.run { ctx with history := h } with
    | .ok _ => []
    | .error e => [s!"{a.name}: {e}"]
  | .top, _ | .bot, _ => []
  | .neg p, h => evaluationErrors ctx p h
  | .conj p q, h | .disj p q, h => evaluationErrors ctx p h ++ evaluationErrors ctx q h
  | .previous w p, h =>
    if inWindow w h h.tail then evaluationErrors ctx p h.tail else []
  | .once w p, h => (List.range h.length).flatMap fun i ↦
    if inWindow w h (h.drop i) then evaluationErrors ctx p (h.drop i) else []
  | .since w p q, h =>
    let suffixes := h.tails.toArray
    (List.range h.length).flatMap fun i ↦
      if inWindow w h suffixes[i]! then
        evaluationErrors ctx q suffixes[i]! ++ (List.range i).flatMap fun j ↦
          evaluationErrors ctx p suffixes[j]!
      else []
  | .within scope p, h => evaluationErrors ctx p (projectAtHead scope h)

def validationErrors (pack : PolicyPack) (ctx : Context) : List String :=
  (pack.rules.filter (fun r ↦ r.applies ctx.request.action)).flatMap fun r ↦
    (evaluationErrors ctx r.condition ctx.history).map (fun e ↦ s!"{r.id}/{e}")

def atomValue (ctx : Context) (a : Check) (h : History) : Bool :=
  ((a.run { ctx with history := h }).toOption).getD false

/-- Evaluates a pack. Any evaluation error at a position the formula looks at denies the call. -/
def decidePolicy (pack : PolicyPack) (ctx : Context) : Decision :=
  let atom := atomValue ctx
  let errors := validationErrors pack ctx
  let reasons := (pack.rules.filter (fun r ↦ r.applies ctx.request.action)).filterMap fun r ↦
    let value := evaluate atom r.condition ctx.history
    if (r.effect == .require && !value) || (r.effect == .forbid && value)
      then some r.id else none
  {
    allow := authorize pack.rules atom ctx.request.action ctx.history && errors.isEmpty
    reasons := if permitted pack.rules atom ctx.request.action ctx.history then reasons
      else "default_deny" :: reasons
    errors := errors
    evidence := ctx.history.map Event.id
  }

theorem decision_sound (pack : PolicyPack) (ctx : Context)
    (h : (decidePolicy pack ctx).allow = true) :
    authorize pack.rules (atomValue ctx) ctx.request.action ctx.history = true := by
  simp only [decidePolicy, Bool.and_eq_true] at h
  exact h.1

theorem decision_no_errors (pack : PolicyPack) (ctx : Context)
    (h : (decidePolicy pack ctx).allow = true) : validationErrors pack ctx = [] := by
  simp only [decidePolicy, Bool.and_eq_true] at h
  simpa using h.2

/-- The pack's meaning in LeanLTL, including the requirement that evaluation raise no errors. -/
def PolicyPack.toLeanLTL (pack : PolicyPack) (ctx : Context) : LeanLTL.TraceSet History :=
  (authorizationLeanLTL pack.rules (atomValue ctx) ctx.request.action).and
    (LeanLTL.TraceSet.const (validationErrors pack ctx = []))

def validatePack (pack : PolicyPack) : Except String Unit := do
  if pack.name.isEmpty then throw "empty policy pack name"
  let ids := pack.rules.map Rule.id
  if ids.eraseDups.length != ids.length then throw "duplicate policy id"
  if pack.rules.isEmpty then throw "empty policy pack"
  for r in pack.rules do
    if r.id.isEmpty || r.actions.isEmpty then throw "empty rule id or action scope"

end LeanGuard
