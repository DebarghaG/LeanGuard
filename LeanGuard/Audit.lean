import Lean.Util.CollectAxioms
import Lean.Elab.Command

namespace LeanGuard.Audit
open Lean Elab Command

/-- Audit explicit roots and every declaration in the supplied namespaces.
Dependencies are collected transitively, including those outside the namespaces. -/
def check (roots namespaces : Array Name) : CommandElabM Unit := do
  let env ← getEnv
  if roots.isEmpty then throwError "supply at least one audit root"
  for root in roots do
    unless env.contains root do throwError "missing audit root: {root}"
  for scope in namespaces do
    unless env.constants.toList.any (fun (name, _) ↦ scope.isPrefixOf name) do
      throwError "empty audit namespace: {scope}"
  let standard := #[``propext, ``Classical.choice, ``Quot.sound]
  let mut checked : Nat := 0
  for (name, _) in env.constants.toList do
    if roots.contains name || namespaces.any (·.isPrefixOf name) then
      let axioms ← Lean.collectAxioms name
      let unexpected := axioms.filter (fun ax ↦ !standard.contains ax)
      unless unexpected.isEmpty do
        throwError "{name} depends on nonstandard axioms: {unexpected}"
      checked := checked + 1
  logInfo m!"LeanGuard axiom audit passed for {checked} declarations"

end LeanGuard.Audit
