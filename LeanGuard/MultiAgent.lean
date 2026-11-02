import LeanGuard.Schema

/-! Bounded delegation and asynchronous task ownership. All budgets are checked and
charged at every ancestor, in the same native admission transition as tool policy.
Agent identifiers are assigned by the trusted host, never by message roles. -/
namespace LeanGuard.MultiAgent
open Lean Data

structure Grant where
  id : String
  parent : String
  principal : String
  actor : String
  workflow : String
  actions : List String
  resources : List String
  peers : List String
  calls : Nat
  amount : Nat
  expires : Nat
  depth : Nat
  deriving FromJson, ToJson, Repr

structure Usage where
  calls : Nat := 0
  amount : Nat := 0
  deriving FromJson, ToJson, Repr

def Usage.fits (u : Usage) (g : Grant) (amount : Nat) : Bool :=
  u.calls < g.calls && u.amount + amount ≤ g.amount

def Usage.reserve (u : Usage) (amount : Nat) : Usage :=
  ⟨u.calls + 1, u.amount + amount⟩

theorem reservation_bound (u : Usage) (g : Grant) (amount : Nat)
    (h : u.fits g amount = true) :
    (u.reserve amount).calls ≤ g.calls ∧ (u.reserve amount).amount ≤ g.amount := by
  simp only [Usage.fits, Bool.and_eq_true, decide_eq_true_eq] at h
  simp only [Usage.reserve]
  omega

def subset (xs ys : List String) : Bool := xs.all ys.contains

def attenuates (child parent : Grant) : Bool :=
  child.principal == parent.principal && child.workflow == parent.workflow &&
  subset child.actions parent.actions && subset child.resources parent.resources &&
  subset child.peers parent.peers && child.calls ≤ parent.calls &&
  child.amount ≤ parent.amount && child.expires ≤ parent.expires && child.depth < parent.depth

theorem attenuation_action (child parent : Grant) (h : attenuates child parent = true)
    (action : String) (mem : action ∈ child.actions) : action ∈ parent.actions := by
  have all : subset child.actions parent.actions = true := by
    simp only [attenuates, Bool.and_eq_true] at h
    exact h.1.1.1.1.1.1.2
  simpa using List.all_eq_true.mp all action mem

inductive TaskPhase where
  | submitted | working | inputRequired | authRequired | completed | canceled | rejected | failed
  deriving Repr, DecidableEq

def TaskPhase.name : TaskPhase → String
  | .submitted => "submitted" | .working => "working"
  | .inputRequired => "input_required" | .authRequired => "auth_required"
  | .completed => "completed" | .canceled => "canceled"
  | .rejected => "rejected" | .failed => "failed"

instance : ToJson TaskPhase := ⟨fun phase ↦ toJson phase.name⟩

def TaskPhase.terminal : TaskPhase → Bool
  | .completed | .canceled | .rejected | .failed => true
  | _ => false

/-- A snapshot may skip unobserved intermediate states; terminal states are absorbing. -/
def taskTransition (old next : TaskPhase) : Bool := !old.terminal || old == next

theorem terminal_absorbing (old next : TaskPhase) (done : old.terminal = true)
    (allowed : taskTransition old next = true) : next = old := by
  have same : old = next := by simpa [taskTransition, done] using allowed
  exact same.symm

structure Task where
  principal : String
  actor : String
  workflow : String
  delegation : String
  peer : String
  id : String
  context : String
  resource : String
  state : TaskPhase
  deriving ToJson, Repr

structure Conversation where
  principal : String
  actor : String
  workflow : String
  delegation : String
  peer : String
  id : String
  resource : String
  deriving ToJson

/-- An admitted operation's first accepted response fixes its target. -/
inductive ResponseTarget where
  | task (id context : String)
  | message (context : String)
  deriving DecidableEq, ToJson, Repr

structure State where
  enabled : Bool := false
  grants : List Grant := []
  usages : List (String × Usage) := []
  revoked : List String := []
  tasks : List Task := []
  contexts : List Conversation := []
  responses : List (String × ResponseTarget) := []
  deriving ToJson

def State.grant (s : State) (id : String) : Except String Grant :=
  match s.grants.find? (·.id == id) with
  | some grant => .ok grant
  | none => .error "unknown delegation"

def State.usage (s : State) (id : String) : Usage :=
  ((s.usages.find? (·.1 == id)).map Prod.snd).getD {}

def State.response (s : State) (request : String) : Option ResponseTarget :=
  (s.responses.find? (·.1 == request)).map Prod.snd

def State.bindResponse (s : State) (request : String) (target : ResponseTarget) :
    Except String State :=
  match s.response request with
  | none => .ok { s with responses := (request, target) :: s.responses }
  | some established =>
    if established = target then .ok s else .error "response target mismatch"

/-- Fuel is bounded by the number of grants. Issue only permits existing parents. -/
def lineage (s : State) : Nat → String → Except String (List Grant)
  | 0, _ => .error "invalid delegation lineage"
  | n + 1, id => do
    let g ← s.grant id
    if g.parent.isEmpty then return [g]
    return g :: (← lineage s n g.parent)

def State.active (s : State) (id : String) (now : Nat) : Except String (List Grant) := do
  let chain ← lineage s (s.grants.length + 1) id
  for g in chain do
    if s.revoked.contains g.id || now > g.expires then throw "expired or revoked delegation"
  return chain

def issue (s : State) (g : Grant) (issuer : String) (now : Nat) : Except String State := do
  if !s.enabled then throw "multi-agent mode is not enabled"
  if [g.id, g.principal, g.actor, g.workflow].any String.isEmpty ||
      g.actions.isEmpty || g.resources.isEmpty || g.peers.isEmpty || g.expires < now then
    throw "invalid delegation"
  if s.grants.any (·.id == g.id) then throw "duplicate delegation"
  if !g.parent.isEmpty then
    let chain ← s.active g.parent now
    let some parent := chain.head? | throw "missing parent"
    if issuer != parent.actor || !attenuates g parent then throw "delegation escalation"
  else
    if !issuer.isEmpty then throw "root delegation requires trusted host authority"
    if s.grants.any (fun old ↦ old.parent.isEmpty && old.principal == g.principal &&
        old.workflow == g.workflow) then throw "workflow already has an authority root"
  return { s with grants := g :: s.grants }

def withinGrant (s : State) (e : Event) (g : Grant) : Bool :=
  g.principal == e.principal && g.workflow == e.workflow &&
    g.actions.contains e.action && g.resources.contains e.resource && g.peers.contains e.peer &&
    !s.revoked.contains g.id && e.time ≤ g.expires && (s.usage g.id).fits g e.amount

/-- Declarative authority meaning, independent of the executable Boolean checks. -/
def WithinGrant (s : State) (e : Event) (g : Grant) : Prop :=
  g.principal = e.principal ∧ g.workflow = e.workflow ∧ e.action ∈ g.actions ∧
    e.resource ∈ g.resources ∧ e.peer ∈ g.peers ∧ g.id ∉ s.revoked ∧ e.time ≤ g.expires ∧
    (s.usage g.id).calls < g.calls ∧ (s.usage g.id).amount + e.amount ≤ g.amount

theorem withinGrant_correct (s : State) (e : Event) (g : Grant) :
    withinGrant s e g = true ↔ WithinGrant s e g := by
  simp [withinGrant, WithinGrant, Usage.fits, and_assoc]

def admissible (s : State) (e : Event) (chain : List Grant) : Bool :=
  chain.head?.any (fun leaf ↦ leaf.actor == e.actor) && chain.all (withinGrant s e)

def AuthorityContract (s : State) (e : Event) (chain : List Grant) : Prop :=
  (∃ leaf rest, chain = leaf :: rest ∧ leaf.actor = e.actor) ∧
    ∀ g ∈ chain, WithinGrant s e g

theorem admissible_correct (s : State) (e : Event) (chain : List Grant) :
    admissible s e chain = true ↔ AuthorityContract s e chain := by
  cases chain <;> simp [admissible, AuthorityContract, List.all_eq_true, withinGrant_correct]

def checkChain (s : State) (e : Event) (chain : List Grant) : Except String (List Grant) :=
  if admissible s e chain then .ok chain
  else .error "interaction exceeds active delegation or shared budget"

theorem checkChain_correct (s : State) (e : Event) (chain accepted : List Grant)
    (h : checkChain s e chain = .ok accepted) : AuthorityContract s e accepted := by
  unfold checkChain at h
  split at h
  next allowed =>
    cases h
    exact (admissible_correct s e chain).mp allowed
  next => contradiction

def authorize (s : State) (e : Event) : Except String (List Grant) := do
  let chain ← lineage s (s.grants.length + 1) e.delegation
  checkChain s e chain

theorem authorize_correct (s : State) (e : Event) (chain : List Grant)
    (h : authorize s e = .ok chain) : AuthorityContract s e chain := by
  cases found : lineage s (s.grants.length + 1) e.delegation with
  | error reason =>
    simp only [authorize, found] at h
    change (Except.error reason : Except String (List Grant)) = .ok chain at h
    contradiction
  | ok ancestors =>
    simp only [authorize, found] at h
    exact checkChain_correct s e ancestors chain h

def charge (s : State) (chain : List Grant) (amount : Nat) : State :=
  { s with usages :=
      chain.map (fun g ↦ (g.id, (s.usage g.id).reserve amount)) ++
        s.usages.filter (fun p ↦ !chain.any (·.id == p.1)) }

/-- Authority can only restrict the existing compiled policy verdict. -/
def restrict (decision : Decision) (authority : Except String (List Grant)) : Decision :=
  match authority with
  | .ok _ => decision
  | .error reason =>
    { decision with
      allow := false
      reasons := decision.reasons ++ ["agents.authority"]
      errors := decision.errors ++ [reason] }

theorem restriction_preserves_policy (d : Decision) (a : Except String (List Grant))
    (h : (restrict d a).allow = true) : d.allow = true := by
  cases a <;> simp_all [restrict]

/-- Evidence must predate admission. Every ancestor's grant remains unrevoked
since its issuance, projected before temporal operators to the workflow. -/
def grantEvent (g : Grant) : Formula Check := eventCheck "delegation_issued" fun r e ↦
  samePrincipal r e && e.kind == "agent_grant" && e.resource == g.id &&
    e.actor == g.actor && e.workflow == g.workflow

def revokeEvent (g : Grant) : Formula Check := eventCheck "delegation_revoked" fun r e ↦
  samePrincipal r e && e.kind == "agent_revoke" && e.resource == g.id

def activeGrant (g : Grant) : Formula Check :=
  .within .workflow (.previous none (.since none (.neg (revokeEvent g)) (grantEvent g)))

def authorityHistory (chain : List Grant) : Formula Check :=
  chain.foldr (fun g rest ↦ .conj (activeGrant g) rest) .top

def historyPack (action : String) (chain : List Grant) : PolicyPack := {
  name := "delegation-history"
  rules := [permit "agents.history_surface" [action],
    require "agents.lifecycle" [action] (authorityHistory chain) "prior, unrevoked ancestor grants"]
}

/-- The live multi-agent verdict conjoins the original pack, temporal contracts,
and the state ledger. The temporal conjunct uses the existing verified evaluator. -/
def decideAdmission (pack : PolicyPack) (c : Context) (authority : Except String (List Grant)) : Decision :=
  let base := restrict (decidePolicy pack c) authority
  match authority with
  | .error _ => base
  | .ok chain =>
    let temporal := decidePolicy (historyPack c.request.action chain) c
    { base with
      allow := base.allow && temporal.allow
      reasons := base.reasons ++ temporal.reasons
      errors := base.errors ++ temporal.errors }


end LeanGuard.MultiAgent
