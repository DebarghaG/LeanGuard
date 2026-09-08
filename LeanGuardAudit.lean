import LeanGuard
import LeanGuardProofs
import LeanGuard.TemporalTests
import LeanGuard.Replay
import LeanGuard.Server
import LeanGuard.Audit

/-! Audit the live/offline entry points and all imported LeanGuard declarations. -/
run_cmd do
  LeanGuard.Audit.check
    #[``LeanGuard.handle, ``LeanGuard.handleWith, ``LeanGuard.serveVerified,
      ``LeanGuard.Replay.run, ``LeanGuard.Replay.handle]
    #[`LeanGuard]
