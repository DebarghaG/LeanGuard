import LeanGuard.Builtins
import LeanGuard.RuntimeCore

namespace LeanGuard

/-- Built-in registry compatibility entry point. Custom servers use `handleWith`. -/
def handle := handleWith packFor

end LeanGuard
