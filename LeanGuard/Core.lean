import Std

/-!
# Native Lean policy language

Policies are typed Lean values. Histories are newest first and contain the current
decision event. Atom meanings are supplied by a typed domain adapter. Temporal
operators quantify over event positions, with inclusive windows in integer seconds.
-/

namespace LeanGuard

structure Event where
  id : String
  time : Nat
  kind : String
  principal : String
  session : String
  action : String
  resource : String
  binding : String
  amount : Nat := 0
  inputJson : String := "{}"
  outputJson : String := "null"
  deriving Repr, DecidableEq

abbrev History := List Event

inductive HistoryScope where
  | principal | conversation | resource
  deriving Repr

def historyKey : HistoryScope → Event → List String
  | .principal, e => [e.principal]
  | .conversation, e => [e.principal, e.session]
  | .resource, e => [e.principal, e.resource]

def project (scope : HistoryScope) (anchor : Event) (h : History) : History :=
  h.filter (fun e ↦ historyKey scope e == historyKey scope anchor)

def projectAtHead (scope : HistoryScope) (h : History) : History :=
  match h with
  | [] => []
  | anchor :: _ => project scope anchor h

theorem project_idempotent (scope : HistoryScope) (anchor : Event) (h : History) :
    project scope anchor (project scope anchor h) = project scope anchor h := by
  simp [project, List.filter_filter]

theorem project_membership (scope : HistoryScope) (anchor e : Event) (h : History) :
    e ∈ project scope anchor h ↔ e ∈ h ∧ historyKey scope e = historyKey scope anchor := by
  simp [project]

inductive Formula (α : Type) where
  | atom : α → Formula α
  | top : Formula α
  | bot : Formula α
  | neg : Formula α → Formula α
  | conj : Formula α → Formula α → Formula α
  | disj : Formula α → Formula α → Formula α
  | previous : Option Nat → Formula α → Formula α
  | once : Option Nat → Formula α → Formula α
  | since : Option Nat → Formula α → Formula α → Formula α
  | within : HistoryScope → Formula α → Formula α
  deriving Repr

namespace Formula
infixr:35 " ⋏ " => conj
infixr:30 " ⋎ " => disj
prefix:40 "∼" => neg
end Formula

def inWindow (window : Option Nat) (h suffix : History) : Bool :=
  match h, suffix with
  | now :: _, past :: _ => past.time ≤ now.time &&
      (window.map (fun w ↦ decide (now.time - past.time ≤ w))).getD true
  | _, _ => false

def evaluate (atom : α → History → Bool) : Formula α → History → Bool
  | .atom a, h => atom a h
  | .top, _ => true
  | .bot, _ => false
  | .neg p, h => !(evaluate atom p h)
  | .conj p q, h => evaluate atom p h && evaluate atom q h
  | .disj p q, h => evaluate atom p h || evaluate atom q h
  | .previous w p, h => inWindow w h h.tail && evaluate atom p h.tail
  | .once w p, h => (List.range h.length).any fun i ↦
      inWindow w h (h.drop i) && evaluate atom p (h.drop i)
  | .since w p q, h => (List.range h.length).any fun i ↦
      inWindow w h (h.drop i) && evaluate atom q (h.drop i) &&
        (List.range i).all (fun j ↦ evaluate atom p (h.drop j))
  | .within scope p, h => evaluate atom p (projectAtHead scope h)

/-- A separate propositional specification of the executable temporal evaluator. -/
def Holds (atom : α → History → Bool) : Formula α → History → Prop
  | .atom a, h => atom a h = true
  | .top, _ => True
  | .bot, _ => False
  | .neg p, h => ¬ Holds atom p h
  | .conj p q, h => Holds atom p h ∧ Holds atom q h
  | .disj p q, h => Holds atom p h ∨ Holds atom q h
  | .previous w p, h => inWindow w h h.tail = true ∧ Holds atom p h.tail
  | .once w p, h => ∃ i ∈ List.range h.length,
      inWindow w h (h.drop i) = true ∧ Holds atom p (h.drop i)
  | .since w p q, h => ∃ i ∈ List.range h.length,
      (inWindow w h (h.drop i) = true ∧ Holds atom q (h.drop i)) ∧
        ∀ j ∈ List.range i, Holds atom p (h.drop j)
  | .within scope p, h => Holds atom p (projectAtHead scope h)

theorem evaluate_correct (atom : α → History → Bool) (p : Formula α) (h : History) :
    evaluate atom p h = true ↔ Holds atom p h := by
  induction p generalizing h <;> simp_all [evaluate, Holds, ← Bool.not_eq_true]

def Formula.atoms : Formula α → List α
  | .atom a => [a]
  | .top | .bot => []
  | .neg p | .previous _ p | .once _ p | .within _ p => p.atoms
  | .conj p q | .disj p q | .since _ p q => p.atoms ++ q.atoms

inductive Effect where
  | permit | forbid | require
  deriving Repr, DecidableEq

structure Rule (α : Type) where
  id : String
  effect : Effect
  actions : List String
  condition : Formula α
  source : String

def Rule.applies (r : Rule α) (action : String) : Bool :=
  r.actions.contains action

def permitted (rules : List (Rule α)) (atom : α → History → Bool)
    (action : String) (h : History) : Bool :=
  rules.any fun r ↦ r.applies action && r.effect == .permit && evaluate atom r.condition h

def requirementsMet (rules : List (Rule α)) (atom : α → History → Bool)
    (action : String) (h : History) : Bool :=
  rules.all fun r ↦ !(r.applies action && r.effect == .require) ||
    evaluate atom r.condition h

def forbidden (rules : List (Rule α)) (atom : α → History → Bool)
    (action : String) (h : History) : Bool :=
  rules.any fun r ↦ r.applies action && r.effect == .forbid && evaluate atom r.condition h

def authorize (rules : List (Rule α)) (atom : α → History → Bool)
    (action : String) (h : History) : Bool :=
  permitted rules atom action h && requirementsMet rules atom action h &&
    !(forbidden rules atom action h)

theorem authorized_requirement (rules : List (Rule α)) (atom : α → History → Bool)
    (action : String) (h : History) (r : Rule α) (mem : r ∈ rules)
    (scope : r.applies action = true) (effect : r.effect = .require)
    (allowed : authorize rules atom action h = true) : Holds atom r.condition h := by
  simp only [authorize, Bool.and_eq_true] at allowed
  have requirements := allowed.1.2
  have each := List.all_eq_true.mp requirements r mem
  have value : evaluate atom r.condition h = true := by
    simpa [scope, effect] using each
  exact (evaluate_correct atom r.condition h).mp value

theorem authorized_no_forbid (rules : List (Rule α)) (atom : α → History → Bool)
    (action : String) (h : History) (r : Rule α) (mem : r ∈ rules)
    (scope : r.applies action = true) (effect : r.effect = .forbid)
    (allowed : authorize rules atom action h = true) : ¬ Holds atom r.condition h := by
  intro holds
  have value := (evaluate_correct atom r.condition h).mpr holds
  have present : forbidden rules atom action h = true := by
    apply List.any_eq_true.mpr
    exact ⟨r, mem, by simp [scope, effect, value]⟩
  simp [authorize, present] at allowed

/-- A dispatch is added only after all native checks and the outer error gate succeed. -/
def reserve (allowed : Bool) (request : Event) (h : History) : History :=
  if allowed then { request with kind := "dispatch" } :: h else h

theorem reservation_retained (request : Event) (h : History) :
    { request with kind := "dispatch" } ∈ reserve true request h := by
  simp [reserve]

theorem deny_no_reservation (request : Event) (h : History) :
    reserve false request h = h := by simp [reserve]

/-- Unknown or absent external decisions may only restrict the native decision. -/
def combineExternal (native : Bool) (external : Option Bool) : Bool :=
  native && external.getD false

theorem external_cannot_override (native : Bool) (external : Option Bool)
    (h : combineExternal native external = true) : native = true := by
  simp [combineExternal] at h
  exact h.1

/-- A monitor checkpoint retains exactly the observed history in v1. -/
structure Monitor where
  history : History := []

def Monitor.observe (m : Monitor) (e : Event) : Monitor := ⟨e :: m.history⟩

def Monitor.run (m : Monitor) (events : List Event) : Monitor :=
  events.foldl Monitor.observe m

theorem replay_history (m : Monitor) (events : List Event) :
    (m.run events).history = events.reverse ++ m.history := by
  induction events generalizing m with
  | nil => rfl
  | cons e es ih =>
    simpa [Monitor.run, Monitor.observe, List.reverse_cons, List.append_assoc] using
      ih (m.observe e)

end LeanGuard
