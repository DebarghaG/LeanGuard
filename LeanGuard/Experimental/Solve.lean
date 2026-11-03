import LeanGuard.PolicyProofs
import LeanGuard.Experimental.Rules
import Lean

/-!
# Policy reasoning with grind components

`guard_solve` runs grind's engine (normalization, congruence closure, E-matching and the
theory solvers) against its own theorem set, populated with `@[guard_rule]`. Closed goals
are computed with `decide`, so a conjunction can mix computation with symbolic reasoning.
`docs/grind.md` explains which parts of grind this reuses and why.
-/

namespace LeanGuard.Experimental
open Lean Meta Elab Tactic

attribute [guard_rule =] decision_leanLTL_correct
attribute [guard_rule →] decision_sound decision_no_errors

namespace GuardSolver

/-- Small default search limits. Any grind configuration field can override them. -/
def defaultConfig : Grind.Config := {
  splits := 4, ematch := 3, gen := 6, genLocal := 6, instances := 256
  trace := false, useSorry := false, abstractProof := false
}

/-- Rejects proofs that depend on `sorry`, including through an auxiliary theorem. -/
def checkProof (goal : MVarId) : MetaM Unit := goal.withContext <| withNewMCtxDepth do
  let proof ← instantiateMVars (mkMVar goal)
  let target ← instantiateMVars (← goal.getType)
  let checked ← mkExpectedTypeHint proof target
  -- Check the types and values of local declarations too; a let-bound `sorry` can hide there.
  let checked ← mkLambdaFVars (← getLCtx).getFVars checked
    (usedOnly := true) (generalizeNondepLet := false)
  let checked ← instantiateMVars checked
  if checked.hasMVar || checked.hasSorry then
    throwError "candidate contains unresolved metavariables or sorry"
  for name in checked.getUsedConstants do
    if (← Lean.collectAxioms name).contains ``sorryAx then
      throwError "candidate depends on sorry through {name}"
  -- A well-typed term may prove the wrong goal, so compare types too. Don't assign the caller's metavariables.
  Meta.check checked

/-- Runs a proof attempt and keeps it only if it is complete and logged no errors.
Otherwise, including on resource exceptions, the state is rolled back. -/
def runChecked (goal : MVarId) (action : TacticM Unit) : TacticM Unit := do
  let initial ← saveState
  let remaining := (← getGoals).tail
  discard <| tryFinally' (do
    setGoals [goal]
    let (_, messages) ← withCapturedMessages <| withoutRecover <| Term.withoutErrToSorry action
    let errors := messages.filter (·.severity == .error)
    unless errors.isEmpty do
      throwError "discharger reported errors:\n{MessageData.joinSep (errors.map (·.data)) m!"\n"}"
    unless (← getUnsolvedGoals).isEmpty do
      throwError "candidate has unproved obligations"
    checkProof goal
    setGoals remaining
    messages.forM logMessage) fun result => do
      if result.isNone then initial.restore true

/-- Builds grind parameters from the `guard_rule` set, grind's `lia` lemmas and any hints. -/
def mkParams (config : Grind.Config) (hints : TSyntaxArray ``Parser.Tactic.grindParam)
    (goal : MVarId) : TacticM Grind.Params := do
  -- In trace mode grind can close stuck branches with `sorry`. Turn that off.
  let config := { config with trace := false, useSorry := false }
  let some rules ← Grind.getExtension? `guard_rule
    | throwError "guard_rule database is not registered"
  let extensions := (← Grind.getLiaExtensions).push (rules.getState (← getEnv))
  let mut params ← Grind.mkParams config extensions
  for hint in hints do
    -- Upstream `eraseCasesTypes` only touches the first extension, and an earlier
    -- parameter may have added another, so merge the case rules before each parameter.
    let casesTypes := params.extensions.foldl (init := {}) fun cases ext =>
      ext.casesTypes.casesMap.foldl (fun cases name eager =>
        cases.insert name (eager || cases.isEagerSplit name)) cases
    params := { params with extensions := params.extensions.mapIdx fun i ext =>
      { ext with casesTypes := if i == 0 then casesTypes else {} } }
    params ← elabGrindParams params #[hint] (only := true) (lax := config.lax)
  -- Same post-parameter setup as `mkGrindParams`, in the same order, including anchors.
  if config.suggestions then
    let mut suggestions : LibrarySuggestions.Config := { caller := some "grind" }
    if let some n := config.maxSuggestions then
      suggestions := { suggestions with maxSuggestions := n }
    params ← elabGrindSuggestions params (← LibrarySuggestions.select goal suggestions)
  if config.locals then params ← elabGrindLocals params
  if params.anchorRefs?.isSome then params := { params with config.clean := false }
  return params

/-- Tries a hypothesis, then `decide`, then splitting a conjunction, then grind. -/
partial def solve (goal : MVarId) (params : Grind.Params) : TacticM Unit :=
    withIncRecDepth <| goal.withContext do
  if (← goal.assumptionCore) then return
  try
    setGoals [goal]
    evalTactic (← `(tactic| decide))
    return
  catch _ => pure ()
  -- Split only conjunctions that are already visible. Unfolding a policy or TraceSet
  -- would remove the term that a registered `guard_rule` pattern matches on.
  let type ← instantiateMVars (← goal.getType)
  if type.isAppOfArity ``And 2 then
    try
      for subgoal in (← goal.apply (mkConst ``And.intro)) do
        solve subgoal params
      return
    catch _ =>
      -- On failure `catch` restores the unsplit goal, so a multipattern can see both sides.
      pure ()
  let result ← Grind.main goal params
  if result.hasFailed then
    throwError "guard_solve could not discharge the obligation\n{← result.toMessageData}"

end GuardSolver

/-- Proves policy goals by computation and grind, using the `guard_rule` lemmas.
Takes grind's configuration and theorem parameters, including `→` and `←`. -/
syntax (name := guardSolve) "guard_solve" optConfig
  (" [" Lean.Parser.Tactic.grindParam,* "]")? : tactic

elab_rules : tactic
  | `(tactic| guard_solve $config:optConfig $[[$hints:grindParam,*]]?) => withMainContext do
    let goal ← getMainGoal
    GuardSolver.runChecked goal do
      let config ← elabGrindConfig config GuardSolver.defaultConfig (logExceptions := false)
      let params ← GuardSolver.mkParams config (hints.map (·.getElems) |>.getD #[]) goal
      -- Roll back every step on failure, not just the grind call.
      Grind.withProtectedMCtx params.config goal fun protectedGoal =>
        GuardSolver.solve protectedGoal params
      setGoals []

end LeanGuard.Experimental
