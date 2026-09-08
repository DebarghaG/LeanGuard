import LeanGuard.Runtime
import LeanGuard.Server

open Lean LeanGuard

def main : IO Unit := serveRegistry packFor
