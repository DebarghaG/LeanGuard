import LeanGuard.Policy
import Lean
import Aesop
import Mathlib.Tactic.Ring
import Mathlib.Tactic.Linarith

/-!
# Experimental, proof-producing repair search

`guard_repair? [candidates]` tries explicit witnesses for an existential repair goal
and suggests an ordinary Lean proof. The goal defines both compliance and the
allowed edits. Search failure means that no candidate was proved, not that no
repair exists. This module is opt-in and does not participate in tool dispatch.
-/

namespace LeanGuard.Experimental
open Lean Meta Elab Tactic

/-- Attach existing policy descriptions to the actual decision, including its error gate.
Descriptions are guidance from the policy author, not certified repair plans. -/
def explain (pack : PolicyPack) (ctx : Context) : Json :=
  let decision := decidePolicy pack ctx
  let applicable := pack.rules.filter fun r ↦ r.applies ctx.request.action
  Json.mkObj [
    ("decision", toJson decision),
    ("blocked_rules", toJson ((applicable.filter fun r ↦ decision.reasons.contains r.id).map
      fun r ↦ Json.mkObj [
        ("id", toJson r.id),
        ("source", toJson r.source),
        ("checks", toJson (r.condition.atoms.map Check.name))])),
    ("permit_rules", toJson ((applicable.filter fun r ↦ r.effect == .permit).map
      fun r ↦ Json.mkObj [("id", toJson r.id), ("source", toJson r.source)]))
  ]

/-- Display denial reasons and policy-author guidance for a concrete, frozen context. -/
macro "#guard_explain " pack:term:max ctx:term:max : command =>
  `(#eval IO.println ((LeanGuard.Experimental.explain $pack $ctx).pretty))

/-- Try explicit candidate edits using existing tactics, or a caller-supplied discharger.
The first fully proved witness wins; order candidates by preference before calling.
Keep trusted facts/history fixed and encode edit restrictions in the existential goal. -/
syntax (name := guardRepair) "guard_repair? " "[" term,* "]"
  (" using " tacticSeq)? : tactic

elab_rules : tactic
  | `(tactic| guard_repair? [$candidates,*] $[using $custom]?) => withMainContext do
    let goal ← getMainGoal
    unless (← whnf (← goal.getType)).isAppOfArity ``Exists 2 do
      throwError "guard_repair? expects an existential goal describing the permitted edits"
    if candidates.getElems.isEmpty then
      throwError "guard_repair? needs at least one candidate"
    if candidates.getElems.size > 32 then
      throwError "guard_repair? accepts at most 32 candidates per experiment"
    let solvers ← match custom with
      | some solver => pure #[solver]
      | none => pure #[← `(tacticSeq| rfl), ← `(tacticSeq| assumption),
          ← `(tacticSeq| simp_all), ← `(tacticSeq| ring), ← `(tacticSeq| linarith),
          ← `(tacticSeq| nlinarith), ← `(tacticSeq| omega), ← `(tacticSeq| decide),
          ← `(tacticSeq| grind), ← `(tacticSeq| aesop)]
    let initial ← saveState
    let remaining := (← getGoals).tail
    for candidate in candidates.getElems do
      for solver in solvers do
        initial.restore true
        setGoals [goal]
        let proofScript ← `(tactic| exact ⟨$candidate, by $solver⟩)
        try
          evalTactic proofScript
          unless (← getUnsolvedGoals).isEmpty do
            throwError "candidate has unproved obligations"
          let proof ← instantiateMVars (mkMVar goal)
          if proof.hasMVar || proof.hasSorry then
            throwError "candidate contains unresolved metavariables or sorry"
          Meta.check proof
          setGoals remaining
          -- Keep source info during execution for tactic linters; omit trailing comments in output.
          let displaySolver : TSyntax ``Parser.Tactic.tacticSeq :=
            ⟨solver.raw.rewriteBottomUp (Syntax.setInfo .none)⟩
          let suggestion ← `(tactic| exact ⟨$candidate, by $displaySolver⟩)
          TryThis.addSuggestion (← getRef) { suggestion := suggestion }
          return
        catch ex =>
          if ex.isInterrupt then throw ex
    initial.restore true
    throwError "guard_repair? could not prove any supplied candidate.\n\
      This is not a proof that repair is impossible. Inspect #guard_explain, supply other \
      candidates, or use `using` with policy-specific lemmas. Missing trusted observations \
      must be obtained through the host.\nGoal: {← goal.getType}"

end LeanGuard.Experimental
