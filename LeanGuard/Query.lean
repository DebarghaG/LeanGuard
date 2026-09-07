import LeanGuard.Policy

namespace LeanGuard
open Lean

inductive EventBasis where
  | requests | dispatches | successes
  deriving Repr, DecidableEq

def EventBasis.kind : EventBasis → String
  | .requests => "request"
  | .dispatches => "dispatch"
  | .successes => "success"

/-- A typed projection of historical tool data; decoding failures remain explicit. -/
structure EventField (α : Type) where
  read : Event → Except String α

def inputField (path : List String) (decode : Json → Except String α) : EventField α :=
  ⟨fun e ↦ do
    let input ← Json.parse e.inputJson
    decode (← path.foldlM Data.field input)⟩

def outputField (path : List String) (decode : Json → Except String α) : EventField α :=
  ⟨fun e ↦ do
    let output ← Json.parse e.outputJson
    decode (← path.foldlM Data.field output)⟩

def inputString (key : String) : EventField String := inputField [key] Json.getStr?
def inputNat (key : String) : EventField Nat := inputField [key] Json.getNat?
def outputBool (key : String) : EventField Bool := outputField [key] Json.getBool?

def pastDataCheck (name action : String) (basis : EventBasis)
    (predicate : Context → Event → Except String Bool) : Formula Check :=
  check name fun c ↦ do
    let some e := c.history.head? | return false
    if !samePrincipal c.request e || e.action != action || e.kind != basis.kind then
      return false
    predicate c e

structure WindowQuery where
  action : String
  basis : EventBasis
  seconds : Nat
  scope : HistoryScope := .principal

def WindowQuery.matches (q : WindowQuery) (request e : Event) : Bool :=
  historyKey q.scope e == historyKey q.scope request && e.action == q.action &&
    e.kind == q.basis.kind && e.time ≤ request.time && request.time - e.time ≤ q.seconds

def WindowQuery.events (q : WindowQuery) (c : Context) : History :=
  c.history.filter (q.matches c.request)

def WindowQuery.count (q : WindowQuery) (c : Context) : Nat := (q.events c).length

def distinctValues [DecidableEq α] (values : List α) : List α := values.eraseDups

def WindowQuery.distinct [DecidableEq α] (q : WindowQuery) (field : EventField α) (c : Context)
    : Except String (List α) := do
  return distinctValues (← (q.events c).mapM field.read)

def WindowQuery.countDistinct [DecidableEq α] (q : WindowQuery) (field : EventField α) (c : Context)
    : Except String Nat := do
  return (← q.distinct field c).length

def WindowQuery.sum (q : WindowQuery) (field : EventField Nat) (c : Context)
    : Except String Nat := do
  return (← (q.events c).mapM field.read).sum

theorem query_membership (q : WindowQuery) (c : Context) (e : Event) :
    e ∈ q.events c ↔ e ∈ c.history ∧ q.matches c.request e = true := by
  simp [WindowQuery.events]

theorem query_window (q : WindowQuery) (c : Context) (e : Event) (h : e ∈ q.events c) :
    e.time ≤ c.request.time ∧ c.request.time - e.time ≤ q.seconds := by
  have matched := (query_membership q c e).mp h |>.2
  simp only [WindowQuery.matches, Bool.and_eq_true, decide_eq_true_eq] at matched
  exact ⟨matched.1.2, matched.2⟩

theorem distinct_membership [DecidableEq α] (values : List α) (value : α) :
    value ∈ distinctValues values ↔ value ∈ values := by
  exact List.mem_eraseDups

theorem distinct_duplicate [DecidableEq α] (values : List α) (value : α) :
    distinctValues (value :: value :: values) = distinctValues (value :: values) := by
  simp [distinctValues, List.eraseDups_cons]

end LeanGuard
