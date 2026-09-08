import LeanGuard.Query
import LeanGuard.Schema

namespace LeanGuard.DogwoodExamples
open Lean Formula Data

def recentApproval : Formula Check :=
  .within .principal (.once (some 3600)
    (pastDataCheck "matching_sale_approval" "ApproveSale" .successes fun c e ↦ do
      return (← (inputString "stock").read e) == (← str c.arguments "stock") &&
        (← (inputNat "shares").read e) == (← nat c.arguments "shares") &&
        (← (outputBool "approved").read e)))

def smallSale : Formula Check := check "at_most_100_shares" fun c ↦ do
  return (← nat c.arguments "shares") ≤ 100

def transfers (basis : EventBasis) : WindowQuery := ⟨"Transfer", basis, 3600, .principal⟩

def tooManyTransfers : Formula Check := check "over_five_requests" fun c ↦
  .ok ((transfers .requests).count c > 5)

def tooManyRecipients : Formula Check := check "over_three_recipients" fun c ↦ do
  return (← (transfers .requests).countDistinct (inputString "user") c) > 3

def excessiveTotal (basis : EventBasis) : Formula Check := check "over_5000" fun c ↦ do
  return (← (transfers basis).sum (inputNat "amount") c) > 5000

def spike : Formula Check := check "above_settled_total" fun c ↦ do
  let prior ← (transfers .successes).sum (inputNat "amount") c
  return (← nat c.arguments "amount") > prior

def confidentialRead : Formula Check := .within .principal (.once none
  (pastDataCheck "confidential_read" "ReadDocument" .successes fun _ e ↦
    (outputBool "confidential").read e))

def saleSchema : Schema := .object ["stock", "shares"]
  [("stock", .string), ("shares", .integer)]

def sales (name : String) (condition : Formula Check) : PolicyPack := withSchemas
  { name := name, rules := [permit "sale" ["SellShares"] condition,
    permit "approval_tool" ["ApproveSale"]] }
  [("SellShares", saleSchema), ("ApproveSale", saleSchema)]

def transferPack (name : String) (condition : Formula Check) (key : String)
    (ty : Schema) : PolicyPack := withSchemas
  { name := name, rules := [permit "base_transfer" ["Transfer"],
    forbid "transfer_limit" ["Transfer"] condition "Dogwood article example"] }
  [("Transfer", .object [key] [(key, ty)])]

def approval := sales "dogwood.approval" recentApproval
def mixed := sales "dogwood.mixed" (smallSale ⋏ recentApproval)
def requestCount := transferPack "dogwood.count" tooManyTransfers "amount" .integer
def distinctRecipients := transferPack "dogwood.distinct" tooManyRecipients "user" .string
def requestSum := transferPack "dogwood.sum" (excessiveTotal .requests) "amount" .integer
def antiSpike := transferPack "dogwood.spike" spike "amount" .integer
def confidentiality : PolicyPack := withSchemas { name := "dogwood.confidential", rules := [
  permit "base" ["ReadDocument", "ContactExternal"],
  forbid "no_contact_after_confidential_read" ["ContactExternal"] confidentialRead
    "Dogwood introduction: no external contact after confidential access"
] } [("ReadDocument", .object [] []), ("ContactExternal", .object [] [])]

/-- Deliberately unsafe response-only policy, used only by the offline conformance runner. -/
def unsafeResponseSum :=
  transferPack "dogwood.unsafe_response_sum" (excessiveTotal .successes) "amount" .integer

def packFor : String → Except String PolicyPack
  | "dogwood.approval" => .ok approval
  | "dogwood.mixed" => .ok mixed
  | "dogwood.count" => .ok requestCount
  | "dogwood.distinct" => .ok distinctRecipients
  | "dogwood.sum" => .ok requestSum
  | "dogwood.spike" => .ok antiSpike
  | "dogwood.confidential" => .ok confidentiality
  | name => .error s!"unknown Dogwood example: {name}"

end LeanGuard.DogwoodExamples
