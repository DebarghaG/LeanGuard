import LeanGuard.MultiAgentProofs
import LeanGuard.TaskContracts
import LeanGuard.A2A

/-! Deterministic adversarial temporal corpus. Expected verdicts are independent
state-fold/pairwise oracles; actual verdicts use the LeanLTL-connected evaluators.
Equal timestamps remain separate causal positions. -/
namespace LeanGuard.MultiAgent.Tests
open Lean TaskContracts LeanLTL

def parent : Grant := ⟨"root", "", "alice", "planner", "workflow", ["read"],
  ["document"], [""], 10, 100, 1000, 2⟩
def child : Grant := { parent with id := "child", parent := "root", actor := "worker", depth := 0 }

def request : Event := {
  id := "request", kind := "request", time := 100, principal := "alice", session := "conversation"
  action := "read", resource := "document", binding := "", actor := "worker"
  workflow := "workflow", delegation := "child"
}

def issued (g : Grant) : Event := { request with
  id := "grant-" ++ g.id, kind := "agent_grant", resource := g.id, actor := g.actor }
def revoked (g : Grant) : Event := { issued g with id := "revoke-" ++ g.id, kind := "agent_revoke" }
def context (past : History) : Context := ⟨request, .null, .null, request :: past⟩

def alphabet : List Event := [issued parent, issued child, revoked parent, revoked child,
  { revoked child with workflow := "foreign" },
  { issued child with principal := "mallory" },
  { issued child with actor := "impostor" },
  { request with kind := "untrusted_model_claim" }]

def words : Nat → List History
  | 0 => [[]]
  | n + 1 => alphabet.flatMap fun e ↦ (words n).map (e :: ·)

def corpus : List History := (List.range 5).flatMap words

/-- Independent chronological state machine, not a call to the temporal evaluator. -/
def oracle (g : Grant) (past : History) : Bool := past.reverse.foldl (fun active e ↦
  if e.principal != "alice" || e.workflow != "workflow" || e.resource != g.id then active
  else if e.kind == "agent_revoke" then false
  else if e.kind == "agent_grant" && e.actor == g.actor then true
  else active) false

set_option maxRecDepth 4096 in
set_option maxHeartbeats 8000000 in
theorem grant_history_corpus : corpus.all (fun past ↦
    evaluate (atomValue (context past)) (authorityHistory [child, parent]) (context past).history ==
      (oracle child past && oracle parent past)) = true := by decide +kernel

theorem scope_before_previous : evaluate (atomValue (context
    [{ revoked child with workflow := "foreign" }, issued child, issued parent]))
    (authorityHistory [child, parent]) (context
    [{ revoked child with workflow := "foreign" }, issued child, issued parent]).history = true := by
  decide

theorem current_event_cannot_issue_its_own_grant :
    evaluate (atomValue (context [])) (activeGrant child) [issued child] = false := by decide

theorem future_dated_grant_is_not_prior_evidence :
    evaluate (atomValue (context [])) (activeGrant child)
      [request, { issued child with time := 101 }] = false := by decide

theorem unrelated_noise_cannot_hide_ancestor_revocation :
    evaluate (atomValue (context [])) (authorityHistory [child, parent])
      ([request] ++ List.replicate 128 { request with kind := "noise" } ++
        [revoked parent, issued child, issued parent]) = false := by decide +kernel

def triple (a b c : TaskPhase) : LTLf.Trace TaskPhase := {
  trace := Trace.unshift a (Trace.unshift b (Trace.singleton c))
  finite := by simp [Trace.Finite]
}

instance (a b c : TaskPhase) : Decidable (LTLf.sat (triple a b c) lifecycleSyntax) := by
  haveI : Decidable ((triple a b c).trace ⊨ lifecycle) := tripleDecidable a b c
  exact decidable_of_iff _ (finite_lifecycle_correct (triple a b c)).symm

def terminalOracle (states : List TaskPhase) : Bool := decide (
  states.Pairwise fun earlier later ↦ earlier.terminal = true → earlier = later)

set_option maxHeartbeats 2000000 in
theorem all_phase_triples : phases.all (fun a ↦ phases.all fun b ↦ phases.all fun c ↦
    decide (LTLf.sat (triple a b c) lifecycleSyntax) == terminalOracle [a, b, c]) = true := by
  decide +kernel

theorem singleton_strong_next_is_false :
    ¬ (Trace.singleton TaskPhase.completed ⊨ TraceSet.true.snext) := by
  simp [TraceSet.sshift_eq_sshift, TraceSet.sat_sshift_iff]

theorem singleton_weak_next_does_not_invent_a_successor :
    Trace.singleton TaskPhase.working ⊨ (TraceSet.false : TraceSet TaskPhase).wnext := by
  simp [TraceSet.wshift_eq_wshift, TraceSet.singleton_sat_wshift]

/-- Reusable source-library temporal algebra preserves a task-resolution contract. -/
theorem resolution_distribution :
    (completed.or (phaseIs .failed)).finally =
      completed.finally.or (phaseIs .failed).finally := by
  exact TraceSet.finally_or_distrib

end LeanGuard.MultiAgent.Tests
