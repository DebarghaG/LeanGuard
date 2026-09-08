import LeanGuard
import LeanGuardProofs
import LeanGuard.TemporalTests
import Lean.Util.CollectAxioms

/-!
Every LeanGuard declaration in the built library is audited transitively. Keeping this
as a default Lake target makes an unfinished proof or a nonstandard axiom a build error.
-/

run_cmd do
  let env ← Lean.getEnv
  let standard := #[``propext, ``Classical.choice, ``Quot.sound]
  let mut checked : Nat := 0
  for (name, _) in env.constants.toList do
    if (`LeanGuard).isPrefixOf name then
      let axioms ← Lean.collectAxioms name
      let unexpected := axioms.filter (fun ax ↦ !standard.contains ax)
      unless unexpected.isEmpty do
        throwError "{name} depends on nonstandard axioms: {unexpected}"
      checked := checked + 1
  if checked == 0 then throwError "empty LeanGuard axiom audit"
  Lean.logInfo m!"LeanGuard axiom audit passed for {checked} declarations"
