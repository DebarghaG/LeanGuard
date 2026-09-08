import Guide
import LeanGuard.Server

def main : IO Unit := LeanGuard.serveRegistry DogwoodGuide.resolve
  (DogwoodGuide.packs.map fun p ↦ (p.name, "DogwoodGuide.sound"))
