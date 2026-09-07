import LeanGuard.Policy

namespace LeanGuard.Domains
open Lean Data

def tauRevision : String := "672227c6b6676edc20d57ea53b7000262aae77b9"

def source (domain clause : String) : String :=
  s!"tau2-bench@{tauRevision}/{domain}: {clause}"

def args (c : Context) := c.arguments
def fact (c : Context) (key : String) := field c.facts key

def stateIs (object : String) (statuses : List String) : Formula Check :=
  check s!"{object}.status" fun c ↦ do
    return statuses.contains (← str (← fact c object) "status")

def ownership (object ownerField : String) : Formula Check :=
  check s!"{object}.owner" fun c ↦ do
    return (← str (← fact c object) ownerField) == (← str c.facts "customer_id")

def argumentOwner (key : String) : Formula Check := check s!"arguments.{key}.owner" fun c ↦ do
  return (← str c.arguments key) == (← str c.facts "customer_id")

def knownIdentity (lookupActions : List String) : Formula Check :=
  check "verified_customer" fun c ↦ do
    let customer ← str c.facts "customer_id"
    let identities := c.history.reverse.filter fun e ↦
      sameConversation c.request e && e.kind == "success" && lookupActions.contains e.action
    return customer != "" && identities.head?.any (fun e ↦ e.resource == customer)

def userProvidedIdentity : Formula Check :=
  check "user_supplied_identity" fun c ↦ do
    let customer ← str c.facts "customer_id"
    return c.history.any fun e ↦ sameConversation c.request e && e.kind == "identity" &&
      e.resource == customer

def stableLookup : Formula Check := check "one_customer_per_conversation" fun c ↦ do
  let customer ← str c.facts "customer_id"
  let candidate ← str c.facts "lookup_customer_id"
  return candidate == "" || customer == "" || customer == candidate

def payment (c : Context) (id : String) : Except String Json := do
  lookup (← field (← fact c "user") "payment_methods") id

def paymentMethod (c : Context) (key : String) : Except String Json := do
  payment c (← str c.arguments key)

def money (j : Json) (key : String) : Except String Int := do
  (← field j key).getInt?

def isGift (p : Json) : Except String Bool := do
  return (← str p "source") == "gift_card"

def covers (p : Json) (amount : Int) : Except String Bool := do
  if ← isGift p then return (← money p "balance") ≥ max amount 0
  return true

def allSame (xs : Array Json) (key value : String) : Except String Bool :=
  Data.all xs fun x ↦ do return (← str x key) == value

def listMember (xs : Array Json) (key value : String) : Except String Bool :=
  Data.any xs fun x ↦ do return (← str x key) == value

def schemaRule (actions : List String) : Policy :=
  require "host.no_overlap" actions singleFlight "single call per conversation and resource"

end LeanGuard.Domains
