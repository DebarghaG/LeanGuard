import Guard
import LeanGuard.Server

def main : IO Unit := LeanGuard.serveVerified DocumentGuard.verified
