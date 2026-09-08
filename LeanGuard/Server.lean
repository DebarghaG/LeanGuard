import LeanGuard.RuntimeCore
import LeanGuard.VerifiedPolicy

namespace LeanGuard
open Lean

/-- Trusted compiled registry; never accept policy code from the acting agent. -/
def serveRegistry (resolve : String → Except String PolicyPack)
    (properties : List (String × String) := []) : IO Unit := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  let mut state : Runtime := {}
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    let response := do
      let request ← Json.parse line
      handleWith resolve state request
    match response with
    | .ok (next, payload) =>
      state := next
      let payload := match payload.getObjVal? "manifest" with
        | .ok info => payload.setObjVal! "manifest" (info.setObjVal! "properties"
            (toJson (properties.filterMap fun (name, property) ↦
              if name == state.domain then some property else none)))
        | .error _ => payload
      output.putStrLn (Json.mkObj [("ok", toJson true), ("result", payload)]).compress
    | .error error =>
      output.putStrLn (Json.mkObj [("ok", toJson false), ("error", toJson error)]).compress
    output.flush

/-- Serve one custom pack without importing LeanGuard's built-in domains. -/
def serve (pack : PolicyPack) : IO Unit :=
  serveRegistry fun name ↦
    if name == pack.name then .ok pack else .error s!"unknown policy pack: {name}"

/-- Proofs are checked at build time and erased from the runtime executable. -/
def serveVerified (policy : VerifiedPolicy) : IO Unit :=
  serveRegistry (fun name ↦
    if name == policy.pack.name then .ok policy.pack else .error s!"unknown policy pack: {name}")
    [(policy.pack.name, policy.property)]

end LeanGuard
