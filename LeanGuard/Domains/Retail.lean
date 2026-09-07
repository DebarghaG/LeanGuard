import LeanGuard.Domains.Common

namespace LeanGuard.Domains.Retail
open Lean Data Formula

def lookups := ["find_user_id_by_email", "find_user_id_by_name_zip"]
def reads := ["get_user_details", "get_order_details", "get_product_details", "get_item_details",
  "list_all_product_types"]
def modifications := ["modify_pending_order_address", "modify_pending_order_payment",
  "modify_pending_order_items"]
def writes := ["cancel_pending_order", "modify_user_address", "return_delivered_order_items",
  "exchange_delivered_order_items"] ++ modifications
def orderWrites := writes.filter (· != "modify_user_address")
def actions := lookups ++ reads ++ writes ++ ["transfer_to_human_agents", "calculate"]

def cancellationReason : Formula Check := check "valid_cancellation_reason" fun c ↦ do
  return ["no longer needed", "ordered by mistake"].contains (← str c.arguments "reason")

def replacementPayment : Formula Check := check "replacement_payment" fun c ↦ do
  let id ← str c.arguments "payment_method_id"
  let order ← fact c "order"
  let history ← array order "payment_history"
  let original ← Data.any history fun p ↦ do
    return (← str p "payment_method_id") == id && (← str p "transaction_type") == "payment"
  let total ← (← array order "items").foldlM (fun n item ↦ do
    return n + (← money item "price")) (0 : Int)
  return !original && (← covers (← payment c id) total)

def validItems (exchange : Bool) : Formula Check := check "valid_item_replacements" fun c ↦ do
  let oldIds ← strings c.arguments "item_ids"
  let newIds ← strings c.arguments "new_item_ids"
  let orderItems ← array (← fact c "order") "items"
  if oldIds.isEmpty || oldIds.size != newIds.size then return false
  let mut difference : Int := 0
  for i in List.range oldIds.size do
    let oldId := oldIds[i]!
    let newId := newIds[i]!
    if oldId == newId then return false
    let candidates ← orderItems.filterM fun item ↦ do return (← str item "item_id") == oldId
    if candidates.size < (oldIds.filter (· == oldId)).size then return false
    let some old := candidates[0]? | throw "item not in order"
    let productId ← str old "product_id"
    let product ← lookup (← fact c "products") productId
    let variant ← lookup (← field product "variants") newId
    if !(← bool variant "available") then return false
    difference := difference + (← money variant "price") - (← money old "price")
  let _ := exchange
  covers (← paymentMethod c "payment_method_id") difference

def validReturn : Formula Check := check "valid_return_and_refund" fun c ↦ do
  let order ← fact c "order"
  let requested ← strings c.arguments "item_ids"
  let items ← array order "items"
  if requested.isEmpty then return false
  for id in requested do
    let matching ← items.filterM fun item ↦ do return (← str item "item_id") == id
    if matching.size < (requested.filter (· == id)).size then return false
  let id ← str c.arguments "payment_method_id"
  let original ← Data.any (← array order "payment_history") fun p ↦ do
    return (← str p "payment_method_id") == id && (← str p "transaction_type") == "payment"
  return original || (← isGift (← payment c id))

def pack : PolicyPack := ⟨"retail", [
  permit "retail.tools" actions,
  schemaRule actions,
  require "retail.stable_identity" lookups stableLookup
    (source "retail" "one customer per conversation"),
  require "retail.identity" (reads ++ writes) (knownIdentity lookups)
    (source "retail" "authenticate even if user id supplied; one customer"),
  require "retail.profile_owner" ["get_user_details", "modify_user_address"]
    (argumentOwner "user_id") (source "retail" "own profile only"),
  require "retail.order_owner" ("get_order_details" :: orderWrites)
    (ownership "order" "user_id") (source "retail" "own orders only"),
  require "retail.confirmation" writes confirmed (source "retail" "confirm database updates"),
  require "retail.status_observed" orderWrites (observed ["get_order_details"])
    (source "retail" "check status before action"),
  require "retail.pending" ("cancel_pending_order" :: modifications)
    (stateIs "order" ["pending"]) (source "retail" "pending orders only"),
  require "retail.delivered" ["return_delivered_order_items", "exchange_delivered_order_items"]
    (stateIs "order" ["delivered"]) (source "retail" "delivered orders only"),
  require "retail.cancel_reason" ["cancel_pending_order"] cancellationReason
    (source "retail" "allowed cancellation reasons"),
  require "retail.modify_once" modifications (neverDispatched modifications)
    (source "retail" "generic action rules: modify once per order"),
  require "retail.exchange_once" ["exchange_delivered_order_items"]
    (neverDispatched ["exchange_delivered_order_items"])
    (source "retail" "exchange once per order"),
  require "retail.payment" ["modify_pending_order_payment"] replacementPayment
    (source "retail" "different payment; gift card covers total"),
  require "retail.modify_items" ["modify_pending_order_items"] (validItems false)
    (source "retail" "same product, available variant, sufficient payment"),
  require "retail.exchange_items" ["exchange_delivered_order_items"] (validItems true)
    (source "retail" "same product, available variant, sufficient payment"),
  require "retail.return" ["return_delivered_order_items"] validReturn
    (source "retail" "ordered items; original payment or existing gift card")
]⟩

end LeanGuard.Domains.Retail
