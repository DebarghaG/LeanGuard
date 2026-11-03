import LeanGuard.Experimental.Solve

/-!
# Experimental, proof-producing repair search

`guard_repair? [candidates]` tries each candidate as the witness for an existential
repair goal and, on success, suggests an ordinary Lean proof. The goal says both what
the policy requires and which edits are acceptable. If every candidate fails, that only
means none was proved. Nothing here runs during tool dispatch.
-/

namespace LeanGuard.Experimental
open Lean Meta Elab Tactic

/-- Pairs each blocking rule in a decision with the description its author wrote. -/
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

/-- Prints the decision for a concrete context and the descriptions of any rules that blocked it. -/
macro "#guard_explain " pack:term:max ctx:term:max : command =>
  `(#eval IO.println ((LeanGuard.Experimental.explain $pack $ctx).pretty))

/-- Tries each candidate in order with `guard_solve`, or with the tactic given after
`using`, and keeps the first one that is fully proved. List candidates in order of
preference. The goal should fix trusted facts and history and state which edits are
acceptable. -/
syntax (name := guardRepair) "guard_repair? " optConfig "[" term,* "]"
  (" with " "[" Lean.Parser.Tactic.grindParam,* "]")?
  (" using " tacticSeq)? : tactic

initialize registerTraceClass `guard.repair

elab_rules : tactic
  | `(tactic| guard_repair? $config:optConfig [$candidates,*]
      $[with [$hints:grindParam,*]]? $[using $custom]?) => withMainContext do
    let goal ← getMainGoal
    unless (← whnf (← goal.getType)).isAppOfArity ``Exists 2 do
      throwError "guard_repair? expects an existential goal describing the permitted edits"
    if candidates.getElems.isEmpty then
      throwError "guard_repair? needs at least one candidate"
    if candidates.getElems.size > 32 then
      throwError "guard_repair? accepts at most 32 candidates per experiment"
    if custom.isSome && (hints.isSome || !config.raw[0].getArgs.isEmpty) then
      throwError "put configuration and lemma hints inside the custom `using` discharger"
    let solver ← match custom with
      | some solver => pure solver
      | none => `(tacticSeq| guard_solve $config:optConfig $[[$hints:grindParam,*]]?)
    let mut failures : Array MessageData := #[]
    for candidate in candidates.getElems do
      let proofScript ← `(tactic| exact ⟨$candidate, by $solver⟩)
      try
        GuardSolver.runChecked goal <| evalTactic proofScript
        for failure in failures do
          trace[guard.repair] failure
        -- Linters need source info while the tactic runs; the printed suggestion drops trailing comments.
        let displaySolver : TSyntax ``Parser.Tactic.tacticSeq :=
          ⟨solver.raw.rewriteBottomUp (Syntax.setInfo .none)⟩
        let suggestion ← `(tactic| exact ⟨$candidate, by $displaySolver⟩)
        TryThis.addSuggestion (← getRef) { suggestion := suggestion }
        return
      catch ex =>
        let detail ← ex.toMessageData.toString
        failures := failures.push m!"Candidate {candidate}:\n{detail}"
    for failure in failures do
      trace[guard.repair] failure
    throwError "guard_repair? could not prove any supplied candidate.\n\
      This is not a proof that repair is impossible. Inspect #guard_explain, supply other \
      candidates, or use `using` with policy-specific lemmas. Missing trusted observations \
      must be obtained through the host.\n\n{MessageData.joinSep failures.toList m!"\n\n"}"

end LeanGuard.Experimental
