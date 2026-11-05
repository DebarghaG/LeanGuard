import ALCFMain
import LeanGuard.Audit

run_cmd do
  LeanGuard.Audit.check #[``ALCF.pack, ``main] #[`ALCF, `LeanGuard]

#print axioms ALCF.pack
