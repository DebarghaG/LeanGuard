import LeanGuard.Temporal
import Lean.Data.Json

namespace LeanGuard
open Lean

structure Context where
  request : Event
  arguments : Json
  facts : Json
  history : History

/-- A named, native Lean predicate. Missing or ill-typed inputs are explicit errors. -/
structure Check where
  name : String
  run : Context → Except String Bool

abbrev Policy := Rule Check

structure PolicyPack where
  name : String
  rules : List Policy

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
  .atom ⟨name, run⟩

def require (id : String) (actions : List String) (condition : Formula Check)
    (source : String) : Policy := ⟨id, .require, actions, condition, source⟩

def permit (id : String) (actions : List String) (condition : Formula Check := .top)
    (source : String := "native policy") : Policy := ⟨id, .permit, actions, condition, source⟩

def forbid (id : String) (actions : List String) (condition : Formula Check)
    (source : String) : Policy := ⟨id, .forbid, actions, condition, source⟩

def samePrincipal (a b : Event) : Bool := a.principal == b.principal
def sameConversation (a b : Event) : Bool := samePrincipal a b && a.session == b.session
def sameResource (a b : Event) : Bool := samePrincipal a b && a.resource == b.resource

def eventCheck (name : String) (p : Event → Event → Bool) : Formula Check :=
  check name fun c ↦ .ok (c.history.head?.any (p c.request))

def confirmedEvent : Formula Check := eventCheck "matching_confirmation" fun r e ↦
  sameConversation r e && e.kind == "confirmed" && e.action == r.action &&
    e.resource == r.resource && e.binding == r.binding && r.binding != ""

def revokedEvent : Formula Check := eventCheck "matching_revocation" fun r e ↦
  sameConversation r e && e.kind == "revoked" && e.binding == r.binding

def usedConfirmation : Formula Check := eventCheck "confirmation_consumed" fun r e ↦
  sameConversation r e && e.kind == "dispatch" && e.binding == r.binding

/-- Confirmation must occur earlier, remain unrevoked, and have no prior reservation. -/
def confirmed : Formula Check :=
  .within .conversation (.previous none ((.since none (.neg revokedEvent) confirmedEvent) ⋏
    .neg (.once none usedConfirmation)))

/-- Add an inclusive age bound measured from the decision, without shifting its clock. -/
def confirmedWithin (seconds : Nat) : Formula Check :=
  confirmed ⋏ .within .conversation (.once (some seconds) confirmedEvent)

def observed (actions : List String) : Formula Check :=
  .within .conversation (.previous none (.once none
    (eventCheck "successful_resource_observation" fun r e ↦
    sameResource r e && sameConversation r e && e.kind == "success" &&
      actions.contains e.action)))

def neverDispatched (actions : List String) : Formula Check :=
  .neg (.once none (eventCheck "resource_dispatch" fun r e ↦
    sameResource r e && e.kind == "dispatch" && actions.contains e.action))

def countEvents (h : History) (p : Event → Bool) : Nat := (h.filter p).length
def sumEvents (h : History) (p : Event → Bool) : Nat :=
  (h.filter p).foldl (fun n e ↦ n + e.amount) 0

def quotaMatches (request : Event) (window : Nat) (e : Event) : Bool :=
  samePrincipal request e && e.kind == "dispatch" &&
    e.time ≤ request.time && request.time - e.time ≤ window

def quota (calls amount window : Nat) : Formula Check := check "dispatch_quota" fun c ↦
  let matching := quotaMatches c.request window
  .ok (countEvents c.history matching < calls &&
    sumEvents c.history matching + c.request.amount ≤ amount)

def singleFlight : Formula Check := check "single_inflight_call" fun c ↦
  .ok (!(c.history.any fun e ↦
    (sameConversation c.request e || sameResource c.request e) && e.kind == "dispatch" &&
    !(c.history.any fun outcome ↦ outcome.id == e.id &&
      (outcome.kind == "success" || outcome.kind == "failure"))))

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
  | .previous _ p, h => evaluationErrors ctx p h.tail
  | .once _ p, h => (List.range h.length).flatMap fun i ↦
    evaluationErrors ctx p (h.drop i)
  | .since _ p q, h => (List.range h.length).flatMap fun i ↦
    evaluationErrors ctx q (h.drop i) ++ (List.range i).flatMap fun j ↦
      evaluationErrors ctx p (h.drop j)
  | .within scope p, h => evaluationErrors ctx p (projectAtHead scope h)

def validationErrors (pack : PolicyPack) (ctx : Context) : List String :=
  (pack.rules.filter (fun r ↦ r.applies ctx.request.action)).flatMap fun r ↦
    (evaluationErrors ctx r.condition ctx.history).map (fun e ↦ s!"{r.id}/{e}")

def atomValue (ctx : Context) (a : Check) (h : History) : Bool :=
  ((a.run { ctx with history := h }).toOption).getD false

/-- Validate every atom used by an applicable rule before Boolean evaluation. -/
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

/-- The complete policy meaning in LeanLTL, including the fail-closed error gate. -/
def PolicyPack.toLeanLTL (pack : PolicyPack) (ctx : Context) : LeanLTL.TraceSet History :=
  (authorizationLeanLTL pack.rules (atomValue ctx) ctx.request.action).and
    (LeanLTL.TraceSet.const (validationErrors pack ctx = []))

def validatePack (pack : PolicyPack) : Except String Unit := do
  let ids := pack.rules.map Rule.id
  if ids.eraseDups.length != ids.length then throw "duplicate policy id"
  if pack.rules.isEmpty then throw "empty policy pack"
  for r in pack.rules do
    if r.id.isEmpty || r.actions.isEmpty then throw "empty rule id or action scope"

end LeanGuard
