import LeanGuard.Replay

open Lean

def main : IO Unit := do
  let stdin ← IO.getStdin
  let stdout ← IO.getStdout
  repeat
    let line ← stdin.getLine
    if line.isEmpty then break
    let response := match Json.parse line >>= LeanGuard.Replay.handle with
      | .ok result => Json.mkObj [("ok", .bool true), ("result", result)]
      | .error error => Json.mkObj [("ok", .bool false), ("error", .str error)]
    stdout.putStrLn response.compress
    stdout.flush
