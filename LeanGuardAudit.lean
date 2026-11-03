import LeanGuard
import LeanGuardProofs
import LeanGuard.TemporalTests
import LeanGuard.Replay
import LeanGuard.Server
import LeanGuard.Audit
import LeanGuard.MultiAgentProofs
import LeanGuard.MultiAgentTests

/-! Axiom audit of the server and replay entry points and every imported LeanGuard declaration. -/
run_cmd do
  LeanGuard.Audit.check
    #[``LeanGuard.handle, ``LeanGuard.handleWith, ``LeanGuard.serveVerified,
      ``LeanGuard.Replay.run, ``LeanGuard.Replay.handle]
    #[`LeanGuard]
