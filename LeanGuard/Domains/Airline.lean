import LeanGuard.Domains.Common

namespace LeanGuard.Domains.Airline
open Lean Data Formula

def reads := ["get_reservation_details", "get_user_details", "list_all_airports",
  "search_direct_flight", "search_onestop_flight", "get_flight_status", "calculate"]
def updates := ["update_reservation_baggages", "update_reservation_flights",
  "update_reservation_passengers", "cancel_reservation"]
def writes := "book_reservation" :: "send_certificate" :: updates
def actions := reads ++ writes ++ ["transfer_to_human_agents"]

structure CancellationEvidence where
  now : Nat
  created : Nat
  flown : Bool
  cancelledByAirline : Bool
  business : Bool
  insured : Bool
  coveredReason : Bool

def canCancel (e : CancellationEvidence) : Bool :=
  !e.flown && ((e.created ≤ e.now && e.now - e.created ≤ 86400) ||
    e.cancelledByAirline || e.business || (e.insured && e.coveredReason))

def CancellationEligible (e : CancellationEvidence) : Prop :=
  e.flown = false ∧ ((e.created ≤ e.now ∧ e.now - e.created ≤ 86400) ∨
    e.cancelledByAirline = true ∨ e.business = true ∨
      (e.insured = true ∧ e.coveredReason = true))

theorem cancellation_correct (e : CancellationEvidence) :
    canCancel e = true ↔ CancellationEligible e := by
  simp [canCancel, CancellationEligible, or_assoc]

def flightStatus (c : Context) (f : Json) : Except String String := do
  let flight ← lookup (← fact c "flights") (← str f "flight_number")
  str (← lookup (← field flight "dates") (← str f "date")) "status"

def notFlown (c : Context) : Except String Bool := do
  Data.all (← array (← fact c "reservation") "flights") fun f ↦ do
    return !["flying", "landed"].contains (← flightStatus c f)

def cancellation : Formula Check := check "cancellation_eligibility" fun c ↦ do
  let r ← fact c "reservation"
  let reason ← str c.facts "cancellation_reason"
  if reason.isEmpty then return false
  let cancelled ← Data.any (← array r "flights") fun f ↦ do
    return (← flightStatus c f) == "cancelled"
  return canCancel {
    now := c.request.time
    created := ← nat r "created_epoch"
    flown := !(← notFlown c)
    cancelledByAirline := cancelled
    business := (← str r "cabin") == "business"
    insured := (← str r "insurance") == "yes"
    coveredReason := ["health", "weather"].contains reason
  }

def activeReservation : Formula Check := check "not_already_cancelled" fun c ↦ do
  let status ← field (← fact c "reservation") "status"
  return status != Json.str "cancelled"

def passengerDetails (ps : Array Json) : Except String Bool :=
  Data.all ps fun p ↦ do
    return !(← str p "first_name").isEmpty && !(← str p "last_name").isEmpty &&
      !(← str p "dob").isEmpty

def passengerUpdate : Formula Check := check "passenger_count_preserved" fun c ↦ do
  let ps ← array c.arguments "passengers"
  return ps.size == (← array (← fact c "reservation") "passengers").size &&
    (← passengerDetails ps)

def freeBags (membership cabin : String) : Nat :=
  (if membership == "gold" then 2 else if membership == "silver" then 1 else 0) +
  (if cabin == "business" then 2 else if cabin == "economy" then 1 else 0)

def baggageValid (c : Context) (passengers : Nat) (cabin : String) : Except String Bool := do
  let total ← nat c.arguments "total_baggages"
  let charged ← nat c.arguments "nonfree_baggages"
  let allowance := passengers * freeBags (← str (← fact c "user") "membership") cabin
  return charged == total - allowance

def baggageUpdate : Formula Check := check "baggage_not_removed" fun c ↦ do
  let r ← fact c "reservation"
  if (← nat c.arguments "total_baggages") < (← nat r "total_baggages") then return false
  if !(← baggageValid c (← array r "passengers").size (← str r "cabin")) then return false
  let p ← paymentMethod c "payment_id"
  match ← str p "source" with
  | "credit_card" => return true
  | "gift_card" =>
    let added := (← nat c.arguments "nonfree_baggages") - (← nat r "nonfree_baggages")
    return (← money p "amount") ≥ 5000 * added
  | _ => return false

def flightCost (c : Context) (fs : Array Json) (cabin : String) (passengers : Nat)
    (old : Array Json := #[]) (oldCabin : String := "") : Except String Int := do
  let mut total := 0
  for f in fs do
    let number ← str f "flight_number"
    let date ← str f "date"
    let retained ← old.filterM fun o ↦ do
      return (← str o "flight_number") == number && (← str o "date") == date &&
        oldCabin == cabin
    if let some retainedFlight := retained[0]? then
      total := total + (← money retainedFlight "price") * passengers
    else
      let flight ← lookup (← fact c "flights") number
      let instanceData ← lookup (← field flight "dates") date
      if (← str instanceData "status") != "available" then throw "flight unavailable"
      let seats ← (← lookup (← field instanceData "available_seats") cabin).getNat?
      if seats < passengers then throw "insufficient seats"
      total := total + (← (← lookup (← field instanceData "prices") cabin).getInt?) * passengers
  return total

def itinerary (c : Context) (fs : Array Json) (origin destination trip : String)
    : Except String Bool := do
  if fs.isEmpty then return false
  let mut location := origin
  let mut visited := false
  let mut seen : List (String × String) := []
  for f in fs do
    let number ← str f "flight_number"
    let date ← str f "date"
    if seen.contains (number, date) then return false
    seen := (number, date) :: seen
    let flight ← lookup (← fact c "flights") number
    if (← str flight "origin") != location then return false
    location := ← str flight "destination"
    visited := visited || location == destination
  return visited && ((trip == "one_way" && location == destination) ||
    (trip == "round_trip" && location == origin))

def booking : Formula Check := check "booking_constraints" fun c ↦ do
  let a := c.arguments
  let ps ← array a "passengers"
  if ps.isEmpty || ps.size > 5 || !(← passengerDetails ps) then return false
  let cabin ← str a "cabin"
  if !["basic_economy", "economy", "business"].contains cabin then return false
  let fs ← array a "flights"
  if !(← itinerary c fs (← str a "origin") (← str a "destination")
      (← str a "flight_type")) then return false
  let flightPrice ← flightCost c fs cabin ps.size
  if !(← baggageValid c ps.size cabin) then return false
  let insurance ← str a "insurance"
  if !["yes", "no"].contains insurance then return false
  let total := flightPrice + (if insurance == "yes" then 3000 * ps.size else 0) +
    5000 * (← nat a "nonfree_baggages")
  let mut certs := 0
  let mut cards := 0
  let mut gifts := 0
  let mut paid : Int := 0
  let mut ids : List String := []
  for p in (← array a "payment_methods") do
    let id ← str p "payment_id"
    if ids.contains id then return false
    ids := id :: ids
    let method ← payment c id
    let amount ← money p "amount"
    if amount < 0 then return false
    paid := paid + amount
    match ← str method "source" with
    | "certificate" =>
      certs := certs + 1
      if (← money method "amount") < amount then return false
    | "credit_card" => cards := cards + 1
    | "gift_card" =>
      gifts := gifts + 1
      if (← money method "amount") < amount then return false
    | _ => return false
  return certs ≤ 1 && cards ≤ 1 && gifts ≤ 3 && paid == total

def flightUpdate : Formula Check := check "flight_change_constraints" fun c ↦ do
  let r ← fact c "reservation"
  let fs ← array c.arguments "flights"
  let old ← array r "flights"
  let oldCabin ← str r "cabin"
  let cabin ← str c.arguments "cabin"
  let sameFlights ← if fs.size != old.size then pure false else
    Data.all (fs.zip old |>.map fun pair ↦ Json.arr #[pair.1, pair.2]) fun pair ↦ do
      let pair ← pair.getArr?
      return (← str pair[0]! "flight_number") == (← str pair[1]! "flight_number") &&
        (← str pair[0]! "date") == (← str pair[1]! "date")
  if !sameFlights && oldCabin == "basic_economy" then return false
  if cabin != oldCabin && !(← notFlown c) then return false
  if !(← itinerary c fs (← str r "origin") (← str r "destination")
      (← str r "flight_type")) then return false
  let n := (← array r "passengers").size
  let total ← flightCost c fs cabin n old oldCabin
  let oldTotal ← old.foldlM (fun n f ↦ do return n + (← money f "price")) (0 : Int)
  let p ← paymentMethod c "payment_id"
  let kind ← str p "source"
  if !["gift_card", "credit_card"].contains kind then return false
  if kind == "credit_card" then return true
  return (← money p "amount") ≥ max (total - oldTotal * n) 0

def compensation : Formula Check := check "compensation_eligibility_and_amount" fun c ↦ do
  let r ← fact c "reservation"
  let member ← str (← fact c "user") "membership"
  let eligible := ["silver", "gold"].contains member || (← str r "insurance") == "yes" ||
    (← str r "cabin") == "business"
  let requested := c.history.any fun e ↦ sameConversation c.request e &&
    e.kind == "compensation_requested" && e.resource == c.request.resource
  let fs ← array r "flights"
  let cancelled ← Data.any fs fun f ↦ do return (← flightStatus c f) == "cancelled"
  let delayed ← Data.any fs fun f ↦ do return (← flightStatus c f) == "delayed"
  let changed := c.history.any fun e ↦ sameResource c.request e &&
    sameConversation c.request e && e.kind == "success" &&
      ["cancel_reservation", "update_reservation_flights"].contains e.action
  let n := (← array r "passengers").size
  let amount ← nat c.arguments "amount"
  return eligible && requested && ((cancelled && amount == 10000 * n) ||
    (delayed && changed && amount == 5000 * n))

def pack : PolicyPack := ⟨"airline", [
  permit "airline.tools" actions,
  schemaRule actions,
  require "airline.identity" ("get_user_details" :: "get_reservation_details" :: writes)
    userProvidedIdentity (source "airline" "user must supply user id"),
  require "airline.user_owner" ["get_user_details", "book_reservation", "send_certificate"]
    (argumentOwner "user_id") (source "airline" "user id correlation"),
  require "airline.reservation_owner" ("get_reservation_details" :: "send_certificate" :: updates)
    (ownership "reservation" "user_id") (source "airline" "reservation and user correlation"),
  require "airline.confirmation" writes confirmed (source "airline" "confirm database updates"),
  require "airline.active" updates activeReservation
    (source "airline" "do not repeat mutation of cancelled reservation"),
  require "airline.observed" ("send_certificate" :: updates) (observed ["get_reservation_details"])
    (source "airline" "confirm reservation facts"),
  require "airline.booking" ["book_reservation"] booking
    (source "airline" "passengers, itinerary, payment limits, baggage, insurance"),
  require "airline.cancel" ["cancel_reservation"] cancellation
    (source "airline" "cancellation eligibility; no flown segment"),
  require "airline.flights" ["update_reservation_flights"] flightUpdate
    (source "airline" "basic economy, itinerary, cabin, seats, payment"),
  require "airline.passengers" ["update_reservation_passengers"] passengerUpdate
    (source "airline" "passenger details; preserve count"),
  require "airline.baggage" ["update_reservation_baggages"] baggageUpdate
    (source "airline" "add but not remove baggage; allowance"),
  require "airline.compensation" ["send_certificate"] compensation
    (source "airline" "requested compensation; eligibility, preceding action, exact amount")
]⟩

end LeanGuard.Domains.Airline
