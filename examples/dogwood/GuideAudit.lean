import GuideMain
import LeanGuard.Audit

run_cmd do
  LeanGuard.Audit.check #[``DogwoodGuide.packs, ``DogwoodGuide.sound,
    ``DogwoodGuide.access_witness, ``main] #[`DogwoodGuide, `LeanGuard]

#print axioms DogwoodGuide.sound
#print axioms DogwoodGuide.access_witness
