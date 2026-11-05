import ALCF
import LeanGuard.Server

def main : IO Unit := LeanGuard.serve ALCF.pack
