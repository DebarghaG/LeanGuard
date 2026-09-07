import LeanGuard.Runtime

open Lean LeanGuard

def main : IO Unit := do
  let input ← IO.getStdin
  let output ← IO.getStdout
  let mut state : Runtime := {}
  repeat
    let line ← input.getLine
    if line.isEmpty then break
    let response := do
      let request ← Json.parse line
      handle state request
    match response with
    | .ok (next, payload) =>
      state := next
      output.putStrLn (Json.mkObj [("ok", toJson true), ("result", payload)]).compress
    | .error error =>
      output.putStrLn (Json.mkObj [("ok", toJson false), ("error", toJson error)]).compress
    output.flush
