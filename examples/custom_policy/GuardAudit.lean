import GuardMain
import LeanGuard.Audit

run_cmd do
  LeanGuard.Audit.check
    #[``DocumentGuard.verified, ``DocumentGuard.safe, ``main]
    #[`DocumentGuard, `LeanGuard]

#print axioms DocumentGuard.safe
