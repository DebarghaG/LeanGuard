import LeanGuard.PolicyProofs
import LeanGuard.Experimental.Rules
import Lean

/-!
# Policy reasoning with grind components

`guard_solve` uses grind's theorem indexing, normalization, congruence closure, E-matching,
and theory solvers with a dedicated policy theorem set. Closed obligations are computed with
`decide`; conjunctions can mix computation with symbolic reasoning. See `docs/grind.md` for the
upstream implementation map and the reasons for this boundary.
-/

namespace LeanGuard.Experimental
open Lean Meta Elab Tactic

attribute [guard_rule =] decision_leanLTL_correct
attribute [guard_rule →] decision_sound decision_no_errors

namespace GuardSolver

/-- Conservative search defaults; all ordinary grind configuration fields remain available. -/
def defaultConfig : Grind.Config := {
  splits := 4, ematch := 3, gen := 6, genLocal := 6, instances := 256
  trace := false, useSorry := false, abstractProof := false
}

/-- Reject unfinished proofs, including sorry hidden behind an auxiliary theorem. -/
def checkProof (goal : MVarId) : MetaM Unit := goal.withContext <| withNewMCtxDepth do
  let proof ← instantiateMVars (mkMVar goal)
  let target ← instantiateMVars (← goal.getType)
  let checked ← mkExpectedTypeHint proof target
  -- Include the types and values of used local declarations, including hidden let-bound sorrys.
  let checked ← mkLambdaFVars (← getLCtx).getFVars checked
    (usedOnly := true) (generalizeNondepLet := false)
  let checked ← instantiateMVars checked
  if checked.hasMVar || checked.hasSorry then
    throwError "candidate contains unresolved metavariables or sorry"
  for name in checked.getUsedConstants do
    if (← Lean.collectAxioms name).contains ``sorryAx then
      throwError "candidate depends on sorry through {name}"
  -- Check the expected type as well as the term, without assigning caller metavariables.
  Meta.check checked

/-- Commit only a complete proof with no reported errors; roll back even on resource exceptions. -/
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

/-- Use grind's parameter elaborator and small arithmetic database with our scoped policy rules. -/
def mkParams (config : Grind.Config) (hints : TSyntaxArray ``Parser.Tactic.grindParam)
    (goal : MVarId) : TacticM Grind.Params := do
  -- Tracing may admit stuck branches upstream. Repair always requires a complete proof.
  let config := { config with trace := false, useSorry := false }
  let some rules ← Grind.getExtension? `guard_rule
    | throwError "guard_rule database is not registered"
  let extensions := (← Grind.getLiaExtensions).push (rules.getState (← getEnv))
  let mut params ← Grind.mkParams config extensions
  for hint in hints do
    -- Upstream erases case rules only from extension zero. Consolidate before each
    -- parameter, since a previous parameter can have added another theorem database.
    let casesTypes := params.extensions.foldl (init := {}) fun cases ext =>
      ext.casesTypes.casesMap.foldl (fun cases name eager =>
        cases.insert name (eager || cases.isEagerSplit name)) cases
    params := { params with extensions := params.extensions.mapIdx fun i ext =>
      { ext with casesTypes := if i == 0 then casesTypes else {} } }
    params ← elabGrindParams params #[hint] (only := true) (lax := config.lax)
  -- Follow mkGrindParams' post-parameter setup, preserving its ordering and anchor handling.
  if config.suggestions then
    let mut suggestions : LibrarySuggestions.Config := { caller := some "grind" }
    if let some n := config.maxSuggestions then
      suggestions := { suggestions with maxSuggestions := n }
    params ← elabGrindSuggestions params (← LibrarySuggestions.select goal suggestions)
  if config.locals then params ← elabGrindLocals params
  if params.anchorRefs?.isSome then params := { params with config.clean := false }
  return params

/-- Discharge a goal with computation, conjunction decomposition, then the shared grind engine. -/
partial def solve (goal : MVarId) (params : Grind.Params) : TacticM Unit :=
    withIncRecDepth <| goal.withContext do
  if (← goal.assumptionCore) then return
  try
    setGoals [goal]
    evalTactic (← `(tactic| decide))
    return
  catch _ => pure ()
  -- Split only explicit conjunctions. Unfolding a policy/TraceSet here would destroy
  -- the term that triggers its registered characterization theorem.
  let type ← instantiateMVars (← goal.getType)
  if type.isAppOfArity ``And 2 then
    try
      for subgoal in (← goal.apply (mkConst ``And.intro)) do
        solve subgoal params
      return
    catch _ =>
      -- TacticM's catch restores the unsplit goal. Keep both sides available to multipatterns.
      pure ()
  let result ← Grind.main goal params
  if result.hasFailed then
    throwError "guard_solve could not discharge the obligation\n{← result.toMessageData}"

end GuardSolver

/-- Solve policy obligations using computation and a dedicated grind theorem database.
Accepts grind configuration and theorem parameters, including directional modifiers. -/
syntax (name := guardSolve) "guard_solve" optConfig
  (" [" Lean.Parser.Tactic.grindParam,* "]")? : tactic

elab_rules : tactic
  | `(tactic| guard_solve $config:optConfig $[[$hints:grindParam,*]]?) => withMainContext do
    let goal ← getMainGoal
    GuardSolver.runChecked goal do
      let config ← elabGrindConfig config GuardSolver.defaultConfig (logExceptions := false)
      let params ← GuardSolver.mkParams config (hints.map (·.getElems) |>.getD #[]) goal
      -- Protect assumption, computation, and decomposition as well as grind's engine.
      Grind.withProtectedMCtx params.config goal fun protectedGoal =>
        GuardSolver.solve protectedGoal params
      setGoals []

end LeanGuard.Experimental
