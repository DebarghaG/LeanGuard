import LeanGuard.PolicyProofs

/-!
Native encodings of the 86 Dogwood guide examples pathValue revision
c6237c88099b3f492ecc5fcee42df06a19224b97. This is an example registry, not a
Dogwood parser. See README.md for the normalization and proof boundary.
-/
namespace DogwoodGuide
open Lean LeanGuard
open LeanGuard.Formula

def pathValue (j : Json) (path : List String) : Except String Json :=
  path.foldlM Data.field j

def textAt (j : Json) (path : List String) : Except String String := do
  (← pathValue j path).getStr?

def intAt (j : Json) (path : List String) : Except String Int := do
  (← pathValue j path).getInt?

def boolAt (j : Json) (path : List String) : Except String Bool := do
  (← pathValue j path).getBool?

def inputText (c : Context) (key : String) := textAt c.arguments [key]
def inputInt (c : Context) (key : String) := intAt c.arguments [key]

def native (name : String) (p : Context → Except String Bool) : Formula Check := check name p

-- The source schema's finite action universe, including its group actions.
def actions : List String := ["Access", "Alert", "Approve", "ApproveSale", "CallTool",
  "Compute", "GetStockInfo", "Grant", "Heartbeat", "Http", "InvokeAgent", "InvokeLLM",
  "Login", "Logout", "Mcp", "Read", "Revoke", "SellShares", "Submit", "Transfer",
  "UnknownTool", "Write"]

def mkExample (name : String) (scope : List String) (condition : Formula Check := .top)
    : PolicyPack := { name, rules := [permit name scope condition "Dogwood guide encoding"] }

def forbidExample (name : String) (scope : List String) (condition : Formula Check)
    (alsoPermit : Bool := false) : PolicyPack := {
  name
  rules := (if alsoPermit then [permit (name ++ ".permit") scope] else []) ++
    [forbid name scope condition "Dogwood guide encoding"]
}

def small (cap : Int) (inclusive : Bool := false) : Formula Check := native "shares_cap" fun c ↦ do
  let n ← inputInt c "shares"
  return if inclusive then n ≤ cap else n < cap

def stockIs (stock : String) : Formula Check := native "stock" fun c ↦ do
  return (← inputText c "stock") == stock

def startsWith (field value : String) : Formula Check := native "startsWith" fun c ↦ do
  return value.isPrefixOf (← inputText c field)

def capByStock (special : String) (cap other : Int) : Formula Check := native "stock_cap" fun c ↦ do
  return (← inputInt c "shares") ≤ if (← inputText c "stock") == special then cap else other

-- Context output, clock, entity ancestry and provider returns are trusted
-- adapter data. They are not invented tool outcomes or user consent.
def outputPresent (c : Context) : Bool := (pathValue c.facts ["context", "output"]).isOk

def proceeds (p : Int → Bool) : Formula Check := native "proceeds" fun c ↦ do
  if !outputPresent c then return false
  return p (← intAt c.facts ["context", "output", "proceeds", "decimal4"])

def oauth : Formula Check := native "principal_type" fun c ↦ do
  return (← textAt c.facts ["principal_type"]) == "Drupe::OAuthUser"

def traders : Formula Check := oauth ⋏ native "entity_ancestry" fun c ↦ do
  return (← Data.strings c.facts "principal_ancestors").contains "Drupe::Team::\"traders\""

def clockCheck (p : Int → Bool) : Formula Check := native "system_clock" fun c ↦ do
  return p (← intAt c.facts ["context", "system", "now", "datetime_ms"])

def providerBool (field : String) : Formula Check := native field fun c ↦
  boolAt c.facts ["providers", field]

def providerInt (field : String) (p : Int → Bool) : Formula Check := native field fun c ↦ do
  return p (← intAt c.facts ["providers", field])

-- Preserve logged data separately from the request-only Cedar context.
def logged (e : Event) (path : List String) : Option Json :=
  ((Json.parse e.factsJson).bind fun j ↦ pathValue j ("logged" :: path)).toOption

def fieldEq (e : Event) (path : List String) (value : Json) : Bool := logged e path == some value

def pins (c : Context) (e : Event) (keys : List String) : Bool := keys.all fun key ↦
  match c.arguments.getObjVal? key with
  | .ok v => fieldEq e ["input", key] v
  | .error _ => false

def matching (c : Context) (e : Event) (action kind : String) (pinned : Bool := true) : Bool :=
  e.action == action && e.kind == kind && (!pinned || samePrincipal c.request e)

def event (action : String) (kind : String := "request") (keys : List String := [])
    (extra : Context → Event → Bool := fun _ _ ↦ true) (pinned : Bool := true) : Formula Check :=
  native (action ++ "." ++ kind) fun c ↦ .ok (c.history.head?.any fun e ↦
    matching c e action kind pinned && pins c e keys && extra c e)

def formerly (p : Formula Check) (seconds : Nat := 3600) (pinned : Bool := true) : Formula Check :=
  let f := Formula.once (some seconds) p
  if pinned then .within .principal f else f

def previous (p : Formula Check) (seconds : Nat := 3600) : Formula Check :=
  .within .principal (.previous (some seconds) p)

def since (left right : Formula Check) (seconds : Nat := 3600) : Formula Check :=
  .within .principal (.since (some seconds) left right)

def login (kind : String := "success") := event "Login" kind ["user"]
def readDocument (kind : String := "success") := event "Read" kind ["user", "document"]
def loginServer := event "Login" "request" ["server"]
def approvedStock (kind : String := "success") := event "ApproveSale" kind ["stock"]
def successful (c : Context) (e : Event) : Bool :=
  pins c e ["user"] && fieldEq e ["output", "result"] (toJson true)

def recent (c : Context) (action kind : String) (seconds : Nat := 3600)
    (pinned : Bool := true) : List Event := c.history.filter fun e ↦
  matching c e action kind pinned && e.time ≤ c.request.time && c.request.time - e.time ≤ seconds

def countTransfers : Formula Check := native "transfer_timepoints" fun c ↦
  .ok ((recent c "Transfer" "request" 3600 false).length == 3)

def pendingTransfers : Formula Check := native "pending_timepoints" fun c ↦
  .ok ((recent c "Transfer" "success").length < (recent c "Transfer" "request").length)

-- One source trace line is one timepoint, even when timestamps are equal.
-- Without formerly, these bodies see only the head, not the whole history.
def currentLoginCount (threshold : Nat) : Formula Check := native "current_login_count" fun c ↦
  .ok (((c.history.take 1).filter (fun e ↦
    matching c e "Login" "request" && pins c e ["server"])).length > threshold)

def currentTransferSum : Formula Check := native "current_distinct_amount_sum" fun c ↦ do
  let rows ← ((c.history.take 1).filter fun e ↦ matching c e "Transfer" "request").mapM fun e ↦ do
    let some j := logged e ["input", "amount"] | throw "missing amount"
    j.getInt?
  return (rows.eraseDups.foldl (· + ·) 0) > 200

def transferSum (kind group : String) (positiveOnly : Bool) (bound : Int) : Formula Check :=
  native "signed_transfer_sum" fun c ↦ do
    let rows ← ((recent c "Transfer" kind).filter fun e ↦
      !positiveOnly || pins c e ["user"]).mapM fun e ↦ do
        let some j := logged e [group, "amount"] | throw "missing amount"
        j.getInt?
    -- Binder (amount,timepoint) retains equal amounts pathValue different positions.
    return ((rows.filter fun n ↦ !positiveOnly || n > 0).foldl (· + ·) 0) > bound

def joined (big : Bool := false) (byPrincipal : Bool := false) : Formula Check :=
  native "joined_login_transfer" fun c ↦ .ok (
    (recent c "Login" "request").any fun l ↦
      (recent c "Transfer" "request").any fun t ↦
        (if byPrincipal then l.principal == t.principal else
          (logged l ["input", "user"]).isSome &&
            logged l ["input", "user"] == logged t ["input", "user"]) &&
        (!big || ((logged t ["input", "amount"]).bind fun j ↦ j.getInt?.toOption).any (· > 100)))

def accessCondition : Formula Check :=
  since (.neg (event "Revoke" "request" ["user", "resource"]))
    (event "Grant" "request" ["user", "resource"])

def packs : List PolicyPack := [
  mkExample "access_not_revoked_since_grant" ["Access"] accessCondition,
  mkExample "alert_exactly_three_transfers" ["Alert"] countTransfers,
  mkExample "alert_heartbeat_and_login_rate" ["Alert"]
    (formerly (event "Heartbeat" "request" ["server"]) ⋏ currentLoginCount 2),
  mkExample "alert_login_and_big_transfer" ["Alert"] (joined true),
  mkExample "alert_login_current_tp" ["Alert"] (currentLoginCount 0),
  mkExample "alert_login_in_last_hour" ["Alert"] (formerly loginServer),
  mkExample "alert_pending_transfers" ["Alert"] pendingTransfers,
  mkExample "alert_same_principal_login_transfer" ["Alert"] (joined false true),
  mkExample "alert_same_user_login_and_transfer" ["Alert"] joined,
  mkExample "alert_some_login" ["Alert"]
    (formerly (event "Login" "request" ["server"] (fun _ _ ↦ true) false) 3600 false),
  mkExample "alert_total_transfer_over_200" ["Alert"] currentTransferSum,
  mkExample "allow_anything" actions,
  mkExample "approve_has_output_guard" ["ApproveSale"] (native "optional_approval" fun c ↦ do
    if !outputPresent c then return false
    boolAt c.facts ["context", "output", "approved"]),
  mkExample "call_cedar_macro_as_argument" ["GetStockInfo"],
  mkExample "call_cedar_macro_is_small" ["SellShares"] (small 100),
  mkExample "call_cedar_macro_with_temporal_leaf" ["Alert"]
    (native "level" (fun c ↦ do return (← inputInt c "level") ≥ 2) ⋏ formerly loginServer),
  mkExample "call_cedar_macros_composed" ["SellShares"]
    ((small 100 ⋎ stockIs "FOO") ⋏ .neg (stockIs "BLOCKED")),
  mkExample "call_temporal_aggregation_macro_count" ["Alert"] (formerly loginServer),
  mkExample "call_temporal_condition_macro_once" ["Write"] (formerly readDocument),
  mkExample "call_temporal_condition_macros_composed" ["Write"]
    (formerly login ⋏ formerly readDocument),
  mkExample "cedar_eligible_not_blocked" ["SellShares"]
    ((small 100 ⋎ stockIs "FOO") ⋏ .neg (stockIs "BLOCKED")),
  mkExample "cedar_is_small_threshold" ["SellShares"] (small 100),
  mkExample "cedar_macro_plus_temporal_leaf" ["Alert"]
    (native "level" (fun c ↦ do return (← inputInt c "level") ≥ 2) ⋏ formerly loginServer),
  mkExample "cedar_semver_gt" actions,
  mkExample "cedar_starts_with_f_like" ["GetStockInfo"] (startsWith "stock" "F"),
  mkExample "cedar_within_cap_if_else" ["SellShares"] (capByStock "FOO" 10 1000),
  mkExample "cond_is_oauth_in_team" ["GetStockInfo"] traders,
  forbidExample "deny_overrides_sell_not_amzn" ["SellShares"] (stockIs "AMZN") true,
  forbidExample "forbid_large_except_amzn" ["SellShares"]
    (.neg (small 100 true) ⋏ .neg (stockIs "AMZN")),
  forbidExample "forbid_read_transfers_over_1000" ["Read"] (transferSum "success" "output" true 1000),
  mkExample "get_amzn_stock_info" ["GetStockInfo"] (stockIs "AMZN"),
  mkExample "heartbeat_scope_alias" ["Alert"] (formerly (event "Heartbeat" "request" ["server"]
    (fun c e ↦ e.resource == c.request.resource))),
  mkExample "login_attempt_custom_kind" ["Read"] (formerly (login "request")),
  mkExample "macro_library_once_is_small" ["SellShares"] (small 100 ⋏ formerly (approvedStock "request")),
  mkExample "max_window_raised" ["Read"] (formerly (event "Login" "success" ["user"] (fun _ _ ↦ true) false) 604800 false),
  mkExample "permit_read_anyone" ["Read"],
  mkExample "principal_is_oauth" ["GetStockInfo"] oauth,
  mkExample "provider_allowed_or_short" ["Read"]
    (providerBool "allowed" ⋎ providerInt "length" (· < 4)),
  forbidExample "provider_digitcount_forbid" ["Read"] (providerInt "digits" (· ≥ 2)) true,
  mkExample "provider_digitcount_operator_ge" ["Read"] (providerInt "digits" (· ≥ 2)),
  mkExample "provider_filter_set_index_decimal" ["Read"] (providerInt "violence_decimal4" (· < 5000)),
  mkExample "provider_int_arithmetic_trusted" ["Read"]
    (native "trusted" (fun c ↦ Data.bool c.arguments "trusted") ⋏ providerInt "digits" (fun n ↦ n + 1 ≤ 3)),
  mkExample "provider_matches_and_not_blocked" ["Read"]
    (providerBool "matched" ⋏ .neg (providerBool "blocked")),
  mkExample "provider_principal_id_allowlist" ["Read"] (providerBool "principal_allowed"),
  mkExample "provider_regex_analyze_fields" ["Read"]
    (providerBool "starts_upper" ⋏ providerInt "digits" (· ≥ 3) ⋏
      native "first_digits" (fun c ↦ do return (← textAt c.facts ["providers", "first_digits"]) == "42")),
  mkExample "provider_regex_matches_uppercase" ["Read"] (providerBool "matched"),
  mkExample "provider_risk_decimal_method" ["Read"] (providerInt "risk_decimal4" (· < 5000)),
  mkExample "read_after_login" ["Read"] (formerly login),
  mkExample "read_after_login_success" ["Read"] (formerly (event "Login" "success" [] successful)),
  mkExample "read_heartbeat_since_login_30s" ["Read"]
    (since (event "Heartbeat" "request" ["user"]) (login "request") 30),
  mkExample "read_login_not_logout" ["Read"]
    (formerly login ⋏ .neg (event "Logout" "success" ["user"])),
  mkExample "read_prev_compute_open_session" ["Read"]
    (previous (event "Compute" "request" ["user"]) ⋏
      since (.neg (event "Logout" "request" ["user"])) (login "request") 86400),
  mkExample "read_prev_login" ["Read"] (previous (login "request")),
  mkExample "read_prev_login_success" ["Read"] (previous (event "Login" "success" [] successful)),
  mkExample "read_since_login" ["Read"] (since (login "request") (login "request")),
  mkExample "sell_after_2024_datetime" ["SellShares"] (clockCheck (· > 1704067200000)),
  mkExample "sell_after_approval_valid_ticker" ["SellShares"]
    (formerly approvedStock ⋏ providerBool "matched"),
  mkExample "sell_comparison_chain" ["SellShares"] (native "share_range" fun c ↦ do
    let n ← inputInt c "shares"
    return n ≥ 1 && n ≤ 1000 && n != 777),
  mkExample "sell_datetime_window" ["SellShares"]
    (clockCheck fun n ↦ n ≥ 1735689600000 && n < 1767225600000),
  mkExample "sell_like_a_prefix" ["SellShares"] (startsWith "stock" "A"),
  mkExample "sell_logical_grouping" ["SellShares"]
    ((small 100 ⋎ stockIs "AMZN") ⋏ .neg (stockIs "BLOCKED")),
  mkExample "sell_nested_if_threshold" ["SellShares"] (native "nested_cap" fun c ↦ do
    let stock ← inputText c "stock"
    return (← inputInt c "shares") ≤ if stock == "AMZN" then 10 else if stock == "MSFT" then 50 else 1000),
  mkExample "sell_nonzero_proceeds_decimal" ["SellShares"] (proceeds (· != 0)),
  mkExample "sell_not_blocked_string" ["SellShares"] (.neg (stockIs "BLOCKED")),
  mkExample "sell_not_test_tickers_like" ["SellShares"] (.neg (startsWith "stock" "TEST_")),
  mkExample "sell_or_approve_action_in" ["SellShares", "ApproveSale"],
  mkExample "sell_shares_eq_scope" ["SellShares"],
  mkExample "sell_shares_temporal_subexpr" ["SellShares"]
    (.neg (small 5 true) ⋏ formerly (event "SellShares")),
  mkExample "sell_small_only" ["SellShares"] (small 50 true),
  mkExample "sell_small_proceeds_decimal_method" ["SellShares"] (proceeds (· < 5000)),
  mkExample "sell_threshold_by_stock" ["SellShares"] (capByStock "AMZN" 10 1000),
  mkExample "sell_two_when_small_amzn" ["SellShares"] (small 100 ⋏ stockIs "AMZN"),
  mkExample "sell_unless_huge" ["SellShares"] (small 10000 true),
  mkExample "sell_when_under_100" ["SellShares"] (small 100),
  mkExample "sell_when_unless_mix" ["SellShares"] (small 1000 true ⋏ .neg (stockIs "BLOCKED")),
  mkExample "sell_zero_proceeds_if_has" ["SellShares"] (proceeds (· == 0)),
  mkExample "simplest_permit" ["GetStockInfo"],
  mkExample "submit_after_approval_injection" ["Submit"]
    (formerly (event "Approve" "request" ["user"] (fun _ e ↦
      fieldEq e ["input", "status"] (toJson "approved")))),
  mkExample "temporal_count_formerly_login" ["Alert"] (formerly loginServer),
  mkExample "temporal_login_then_read" ["Write"] (formerly login ⋏ formerly readDocument),
  mkExample "temporal_once_read_recent" ["Read", "Write"] (formerly (readDocument "request")),
  mkExample "temporal_sum_formerly_transfer" ["Alert"] (transferSum "request" "input" false 100),
  mkExample "traders_is_in_group_scope" ["GetStockInfo"] traders,
  mkExample "transfer_prev_nested_conj" ["Transfer"] (previous
    (login "request" ⋏ event "Login" "request" [] (fun _ e ↦
      fieldEq e ["input", "server"] (toJson "s1"))) 7200),
  mkExample "write_after_read" ["SellShares"] (formerly approvedStock),
  mkExample "write_after_read_formerly" ["Write"] (formerly readDocument)
]

def resolve (name : String) : Except String PolicyPack :=
  match packs.find? (·.name == name) with
  | some pack => .ok pack
  | none => .error s!"unknown guide example: {name}"

/-- Every encoded decision is equivalent to its LeanLTL meaning, including
errors. This does not assert equivalence to Dogwood's Rust interpreter. -/
theorem sound (pack : PolicyPack) (c : Context) :
    (decidePolicy pack c).allow = true ↔ historyTrace c.history ⊨ pack.toLeanLTL c :=
  decision_leanLTL_correct pack c

/-- Access requires a grant witness in the hour and no matching revocation
pathValue any subsequent position in the principal's projected history. -/
theorem access_witness (c : Context)
    (allowed : (decidePolicy (mkExample "access_not_revoked_since_grant" ["Access"] accessCondition) c).allow = true) :
    ∃ i ∈ List.range (projectAtHead .principal c.history).length,
      (inWindow (some 3600) (projectAtHead .principal c.history)
        ((projectAtHead .principal c.history).drop i) = true ∧
       Holds (atomValue c) (event "Grant" "request" ["user", "resource"])
         ((projectAtHead .principal c.history).drop i)) ∧
      ∀ j ∈ List.range i,
        ¬ Holds (atomValue c) (event "Revoke" "request" ["user", "resource"])
          ((projectAtHead .principal c.history).drop j) := by
  have h := decision_sound _ c allowed
  simp only [mkExample, authorize, permitted, List.any_cons, List.any_nil,
    Bool.or_false, Bool.and_eq_true] at h
  have accepted := (evaluate_correct _ _ _).mp h.1.1.2
  exact accepted

end DogwoodGuide
