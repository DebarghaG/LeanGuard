import LeanGuard.Experimental.TemporalRepair
import LeanGuard.Audit

/-!
# Repair search against LeanLTL temporal semantics

All histories are frozen, newest first, and synthetic. The only call edit is a
payload selected from three choices; the requested payload is fixed by the goal.
The fixture uses the payload as its approval binding for one fixed action/resource.
This is not a replacement for the host's proposal normalization or approval flow.
-/

namespace LeanGuard.Experimental.TemporalStress
open Lean

def value (choice : Fin 3) : String := ["typo", "", "approved"][choice.val]!

def event (kind : String) (time : Nat) : Event := {
  id := kind, kind := kind, time := time, principal := "alice", session := "temporal-repair",
  action := "write", resource := "document", binding := "approved"
}

def readAt (time : Nat) : Event := { event "success" time with action := "read" }

def context (past : History) (choice : Fin 3) : Context :=
  let arguments := Json.mkObj [("value", toJson (value choice))]
  let request := { event "request" 100 with
    binding := value choice, inputJson := arguments.compress }
  ⟨request, arguments, Json.mkObj [("requested_value", .str "approved")], request :: past⟩

def pack : PolicyPack := { name := "temporal-repair", rules := [
  permit "write" ["write"],
  require "read_first" ["write"] (observed ["read"]) "successful read of this resource",
  require "approval" ["write"] (confirmedWithin 10) "unused, unrevoked approval within 10 seconds"
] }

def good : History := [readAt 95, event "confirmed" 90]
def expired : History := [readAt 95, event "confirmed" 89]
def revoked : History := [readAt 95, event "revoked" 94, event "confirmed" 90]
def consumed : History := [readAt 95, event "dispatch" 94, event "confirmed" 90]
def foreignNoise : History :=
  [{ event "revoked" 99 with session := "other" }, readAt 95, event "confirmed" 90]
def renewed : History :=
  [readAt 99, event "confirmed" 98, event "revoked" 94, event "confirmed" 90]

def compliant (past : History) (choice : Fin 3) : Prop :=
  historyTrace (context past choice).history ⊨ pack.toLeanLTL (context past choice)

instance (past : History) (choice : Fin 3) : Decidable (compliant past choice) :=
  inferInstanceAs (Decidable (_ ⊨ _))

theorem full_policy_repair : ∃ choice : Fin 3, choice = 2 ∧ compliant good choice := by
  guard_repair? [0, 1, 2]

theorem replayed_suggestion : ∃ choice : Fin 3, choice = 2 ∧ compliant good choice := by
  exact ⟨2, by decide⟩

theorem scoped_repair : ∃ choice : Fin 3, choice = 2 ∧ compliant foreignNoise choice := by
  guard_repair? [0, 1, 2]

theorem newer_approval_repair : ∃ choice : Fin 3, choice = 2 ∧ compliant renewed choice := by
  guard_repair? [0, 1, 2]

-- Expiry, revocation, and consumption cannot be repaired by any available payload edit.
theorem expired_has_no_repair : ¬ ∃ choice : Fin 3, compliant expired choice := by decide
theorem revoked_has_no_repair : ¬ ∃ choice : Fin 3, compliant revoked choice := by decide
theorem consumed_has_no_repair : ¬ ∃ choice : Fin 3, compliant consumed choice := by decide

set_option linter.unreachableTactic false in
theorem temporal_failure_restores_search : ∃ choice : Fin 3, compliant good choice := by
  fail_if_success
    have : ∃ choice : Fin 3, compliant revoked choice := by
      guard_repair? [0, 1, 2] using decide
  guard_repair? [0, 1, 2] using decide

-- A valid proof for one snapshot is not valid after consuming or revoking its approval.
theorem repaired_proof_is_not_monotone :
    compliant good 2 ∧ ¬ compliant (event "revoked" 99 :: good) 2 ∧
      ¬ compliant (event "dispatch" 99 :: good) 2 := by decide

theorem history_and_facts_unchanged (past : History) (a b : Fin 3) :
    (context past a).history.tail = past ∧
      (context past a).facts = (context past b).facts := by
  exact ⟨rfl, rfl⟩

structure PolicyCase where
  name : String
  past : History
  expected : Bool

def policyCases : List PolicyCase := [
  ⟨"inclusive approval boundary", good, true⟩,
  ⟨"expired approval", expired, false⟩,
  ⟨"future approval", [readAt 95, event "confirmed" 101], false⟩,
  ⟨"missing history", [], false⟩,
  ⟨"missing read", [event "confirmed" 90], false⟩,
  ⟨"failed read", [{ readAt 95 with kind := "failure" }, event "confirmed" 90], false⟩,
  ⟨"wrong resource", [{ readAt 95 with resource := "other" }, event "confirmed" 90], false⟩,
  ⟨"wrong session", [{ readAt 95 with session := "other" }, event "confirmed" 90], false⟩,
  ⟨"wrong principal", [{ readAt 95 with principal := "bob" }, event "confirmed" 90], false⟩,
  ⟨"revoked approval", revoked, false⟩,
  ⟨"consumed approval", consumed, false⟩,
  ⟨"foreign revocation", foreignNoise, true⟩,
  ⟨"newer approval after revocation", renewed, true⟩,
  ⟨"reusing a consumed binding",
    [readAt 99, event "confirmed" 98, event "dispatch" 94, event "confirmed" 90], false⟩,
  ⟨"equal timestamps still have strict position order", [readAt 100, event "confirmed" 100], true⟩,
  ⟨"recent noise cannot refresh an old approval",
    [event "noise" 99, readAt 98, event "confirmed" 0], false⟩
]

-- Explicit expected outcomes; this also checks that the two unintended payloads stay denied.
theorem policy_matrix : policyCases.all (fun c ↦ (List.finRange 3).all fun choice ↦
    decide (compliant c.past choice) == (c.expected && choice == 2)) = true := by decide +kernel

def times : List Nat := [89, 90, 95, 100, 101]

-- Cross product: clocks × event order × conversation scope × read outcome × payload.
-- The oracle uses explicit order/window arithmetic, not the policy evaluator.
theorem time_order_grid : times.all (fun readTime ↦ times.all fun approvalTime ↦
    [false, true].all fun readFirst ↦ [false, true].all fun foreign ↦
      [false, true].all fun failed ↦ (List.finRange 3).all fun choice ↦
        let read := { readAt readTime with
          session := if foreign then "other" else "temporal-repair",
          kind := if failed then "failure" else "success" }
        let approval := event "confirmed" approvalTime
        let past := if readFirst then [read, approval] else [approval, read]
        let ordered := if readFirst then approvalTime ≤ readTime else readTime ≤ approvalTime
        let expected := !foreign && !failed && choice == 2 && decide ordered &&
          decide (readTime ≤ 100 ∧ approvalTime ≤ 100 ∧ 100 - approvalTime ≤ 10)
        decide (compliant past choice) == expected) = true := by decide +kernel

def tag (name : String) (history : History) : Bool :=
  if name == "suffix_two" then history.length == 2
  else history.head?.any (fun e ↦ e.kind == name)

structure TemporalCase where
  name : String
  formula : Formula String
  history : History
  expected : Bool

def temporalCases : List TemporalCase := [
  ⟨"empty strong previous", .previous none .top, [], false⟩,
  ⟨"empty once", .once none .top, [], false⟩,
  ⟨"empty since", .since none .top .top, [], false⟩,
  ⟨"empty Boolean negation", .neg .bot, [], true⟩,
  ⟨"singleton strong previous", .previous none (.neg .bot), [event "now" 100], false⟩,
  ⟨"inclusive once window", .once (some 10) (.atom "confirmed"),
    [event "now" 100, event "confirmed" 90], true⟩,
  ⟨"expired once window", .once (some 9) (.atom "confirmed"),
    [event "now" 100, event "confirmed" 90], false⟩,
  ⟨"unbounded still excludes future", .once none (.atom "confirmed"),
    [event "now" 100, event "confirmed" 101], false⟩,
  ⟨"zero window accepts equal timestamps", .previous (some 0) (.atom "confirmed"),
    [event "now" 100, event "confirmed" 100], true⟩,
  ⟨"nested windows re-anchor", .previous none (.once (some 10) (.atom "confirmed")),
    [event "now" 100, event "noise" 90, event "confirmed" 80], true⟩,
  ⟨"nested window expiry", .previous none (.once (some 9) (.atom "confirmed")),
    [event "now" 100, event "noise" 90, event "confirmed" 80], false⟩,
  ⟨"since excludes its witness from the left", .since none (.neg (.atom "confirmed"))
    (.atom "confirmed"), [event "now" 100, event "confirmed" 90], true⟩,
  ⟨"since checks intervening positions even at future timestamps",
    .since (some 10) (.neg (.atom "revoked")) (.atom "confirmed"),
    [event "now" 100, event "revoked" 105, event "confirmed" 90], false⟩,
  ⟨"projection before previous", .within .conversation (.previous none (.atom "confirmed")),
    [event "now" 100, { event "noise" 95 with session := "other" },
      event "confirmed" 90], true⟩,
  ⟨"projection after previous re-anchors differently",
    .previous none (.within .conversation (.atom "confirmed")),
    [event "now" 100, { event "noise" 95 with session := "other" },
      event "confirmed" 90], false⟩,
  ⟨"atoms can inspect their complete suffix", .once (some 10) (.atom "suffix_two"),
    [event "now" 100, event "noise" 95, event "confirmed" 90], true⟩
]

theorem temporal_matrix : temporalCases.all (fun c ↦
    decide (historyTrace c.history ⊨ c.formula.toLeanLTL tag) == c.expected) = true := by
  decide +kernel

def noisyPast (length : Nat) : History :=
  (List.range length).map (fun i ↦ { event "noise" 99 with id := s!"noise-{i}" }) ++ good

theorem long_history_repair : ∃ choice : Fin 3, compliant (noisyPast 128) choice := by
  guard_repair? [0, 1, 2] using decide +kernel

def nestedPrevious : Nat → Formula String
  | 0 => .atom "confirmed"
  | depth + 1 => .previous none (nestedPrevious depth)

def deepHistory : History :=
  event "request" 100 :: List.replicate 32 (event "noise" 99) ++ [event "confirmed" 90]

theorem deep_formula_repair : ∃ choice : Fin 3,
    historyTrace deepHistory ⊨ (nestedPrevious 33).toLeanLTL
      (fun name h ↦ tag name h && value choice == "approved") := by
  guard_repair? [0, 1, 2] using decide +kernel

theorem deep_strong_previous_boundary :
    ¬ (historyTrace deepHistory ⊨ (nestedPrevious 34).toLeanLTL tag) := by decide

-- Use an existing LeanLTL distribution theorem to guide a symbolic repair proof.
-- The arbitrary context family and edit constraint remain fixed throughout the search.
theorem rewrite_guided_repair (ctx : α → Context) (permitted : α → Prop)
    (_original repaired : α) (w : Option Nat) (p q : Formula String)
    (intent : permitted repaired)
    (evidence : historyTrace (ctx repaired).history ⊨
      (Formula.once w (.disj p q)).toLeanLTL tag) :
    ∃ edit, permitted edit ∧ (historyTrace (ctx edit).history ⊨
      (Formula.disj (.once w p) (.once w q)).toLeanLTL tag) := by
  guard_repair? [_original, repaired] using
    exact ⟨intent, by rw [← toLeanLTL_once_disj]; exact evidence⟩

def malformed : Formula Check := check "malformed" fun _ ↦ .error "missing trusted fact"
def errorPack : PolicyPack := { pack with
  rules := require "error" ["write"] (.top ⋎ malformed)
    "validate even a true disjunction" :: pack.rules }

-- Bare temporal truth cannot bypass policy validation.
theorem temporal_truth_is_not_full_admission :
    (historyTrace (context good 2).history ⊨
      (Formula.top ⋎ malformed).toLeanLTL (atomValue (context good 2))) ∧
    ¬ (historyTrace (context good 2).history ⊨ errorPack.toLeanLTL (context good 2)) := by
  decide

theorem malformed_has_no_repair : ¬ ∃ choice : Fin 3,
    historyTrace (context good choice).history ⊨ errorPack.toLeanLTL (context good choice) := by
  decide

#eval IO.println s!"LTL stress: {policyCases.length * 3} policy/payload cases, \
  {temporalCases.length} temporal boundary cases, {times.length ^ 2 * 8 * 3} grid cases"
#print axioms full_policy_repair
#print axioms rewrite_guided_repair
#print axioms long_history_repair
#print axioms deep_formula_repair
#print axioms repair_iff_leanLTL
run_cmd do
  LeanGuard.Audit.check #[``full_policy_repair, ``repair_iff_leanLTL]
    #[`LeanGuard.Experimental.TemporalStress, `LeanGuard.Experimental.decidablePolicyLeanLTL]

end LeanGuard.Experimental.TemporalStress
