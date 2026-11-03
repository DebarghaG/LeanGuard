import LeanGuard.Builtins
import LeanGuard.RuntimeCore

namespace LeanGuard

/-- Request handler for the built-in packs. Custom servers call `handleWith` directly. -/
def handle := handleWith packFor

end LeanGuard
