import LeanGuard.Domains.Common

namespace LeanGuard.Domains.Telecom
open Lean Data Formula

def lookups := ["get_customer_by_phone", "get_customer_by_id", "get_customer_by_name"]
def reads := ["get_details_by_id", "get_bills_for_customer", "get_data_usage"]
def lineWrites :=
  ["suspend_line", "resume_line", "enable_roaming", "disable_roaming", "refuel_data"]
def writes := "send_payment_request" :: lineWrites
def actions := lookups ++ reads ++ writes ++ ["transfer_to_human_agents"]

def lineOwned : Formula Check := check "line_ownership" fun c ↦ do
  let customer ← fact c "user"
  return (← strings customer "line_ids").contains (← str c.arguments "line_id")

def detailOwned : Formula Check := check "detail_ownership" fun c ↦ do
  let id ← str c.arguments "id"
  let user ← fact c "user"
  match ← str c.facts "detail_type" with
  | "customer" => return id == (← str c.facts "customer_id")
  | "bill" => return (← strings user "bill_ids").contains id
  | "line" => return (← strings user "line_ids").contains id
  | "plan" => return true
  | "device" =>
    Data.any (← array c.facts "customer_lines") fun line ↦ do
      return (← field line "device_id") == Json.str id
  | _ => return false

def paymentRequest : Formula Check := check "overdue_and_no_other_payment_request" fun c ↦ do
  let bill ← fact c "bill"
  let customer ← fact c "user"
  let billId ← str c.arguments "bill_id"
  let bills ← array c.facts "bills"
  return (← strings customer "bill_ids").contains billId &&
    (← str bill "status") == "Overdue" &&
    (← Data.all bills fun b ↦ do return (← str b "status") != "Awaiting Payment")

/-- A recorded bill must expose the target's identity, status and amount. -/
def billRecorded (customer id : String) (bill : Json) : Bool :=
  (str bill "bill_id").toOption == some id &&
  (str bill "customer_id").toOption == some customer &&
  (str bill "status").isOk &&
  (match field bill "total_due" with | .ok (.num _) => true | _ => false)

def recordedBills (customer id : String) (bills : List Json) : Bool :=
  bills.any (billRecorded customer id)

theorem billRecorded_identity (customer id : String) (bill : Json)
    (h : billRecorded customer id bill = true) :
    (str bill "bill_id").toOption = some id ∧
    (str bill "customer_id").toOption = some customer := by
  simp only [billRecorded, Bool.and_eq_true, beq_iff_eq] at h
  exact h.1.1

theorem recordedBills_witness (customer id : String) (bills : List Json)
    (h : recordedBills customer id bills = true) :
    ∃ bill ∈ bills, billRecorded customer id bill = true := List.any_eq_true.mp h

def billObserved : Formula Check := check "bill_or_customer_bills_observed" fun c ↦ do
  let customer ← str c.facts "customer_id"
  return c.history.any fun e ↦
    sameConversation c.request e && e.kind == "success" && e.time ≤ c.request.time &&
    (match Json.parse e.outputJson with
    | .ok output =>
      if e.action == "get_details_by_id" && e.resource == c.request.resource then
        billRecorded customer c.request.resource output
      else if e.action == "get_bills_for_customer" && e.resource == customer then
        match output.getArr? with
        | .ok bills => recordedBills customer c.request.resource bills.toList
        | .error _ => false
      else false
    | .error _ => false)

def resume : Formula Check := check "resume_eligibility" fun c ↦ do
  let line ← fact c "line"
  let endDate ← field line "contract_end_epoch"
  let unexpired ← match endDate with
    | .null => pure true
    | value => do pure (c.request.time ≤ (← value.getNat?))
  return unexpired && (← str line "status") == "Suspended" &&
    (← Data.all (← array c.facts "bills") fun b ↦ do return (← str b "status") != "Overdue")

def refueling : Formula Check := check "refueling_limit" fun c ↦ do
  let amount ← nat c.arguments "gb_amount_milli"
  let line ← fact c "line"
  let plan ← fact c "plan"
  return 0 < amount && amount ≤ 2000 &&
    (← nat line "data_used_gb_milli") > (← nat plan "data_limit_gb_milli")

def suspend : Formula Check := check "suspension_reason" fun c ↦ do
  let line ← fact c "line"
  let reason ← str c.arguments "reason"
  let overdue ← Data.any (← array c.facts "bills") fun b ↦ do
    return (← str b "status") == "Overdue"
  let expired ← match ← field line "contract_end_epoch" with
    | .null => pure false
    | value => do pure ((← value.getNat?) < c.request.time)
  return (reason == "overdue bill" && overdue) || (reason == "contract expired" && expired)

def roaming : Formula Check := check "travelling_and_roaming_disabled" fun c ↦ do
  let travelling := c.history.any fun e ↦ sameConversation c.request e &&
    e.kind == "travelling" && e.resource == c.request.resource
  return travelling && !(← bool (← fact c "line") "roaming_enabled")

def pack : PolicyPack := ⟨"telecom", [
  permit "telecom.tools" actions,
  schemaRule actions,
  require "telecom.stable_identity" lookups stableLookup
    (source "telecom" "customer identity correlation"),
  require "telecom.detail_owner" ["get_details_by_id"] detailOwned
    (source "telecom" "customer records only; plan information is public"),
  require "telecom.identity" (reads ++ writes) (knownIdentity lookups)
    (source "telecom" "identify customer first"),
  require "telecom.customer" ("get_bills_for_customer" :: "get_data_usage" :: writes)
    (argumentOwner "customer_id") (source "telecom" "customer correlation"),
  require "telecom.line_owner" ("get_data_usage" :: lineWrites) lineOwned
    (source "telecom" "customer line correlation"),
  require "telecom.payment_request" ["send_payment_request"] paymentRequest
    (source "telecom" "overdue bill; only one awaiting payment"),
  require "telecom.bill_observed" ["send_payment_request"]
    billObserved
    (source "telecom" "check bill status and amount"),
  require "telecom.resume" ["resume_line"] resume
    (source "telecom" "all overdue bills paid; contract not expired"),
  require "telecom.refuel" ["refuel_data"] refueling
    (source "telecom" "exceeded plan; positive refuel at most 2GB"),
  require "telecom.refuel_confirm" ["refuel_data"] confirmed
    (source "telecom" "confirm quantity and price"),
  require "telecom.suspend" ["suspend_line"] suspend
    (source "telecom" "overdue bill or expired contract"),
  require "telecom.roaming" ["enable_roaming"] roaming
    (source "telecom" "travelling outside home network; check roaming status")
]⟩

end LeanGuard.Domains.Telecom
