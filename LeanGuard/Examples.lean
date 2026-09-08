import LeanGuard.Policy

namespace LeanGuard.Examples
open Formula

def recentlyRead : Formula Check :=
  .within .conversation (.once (some 3600)
    (eventCheck "read_same_document" fun request past ↦
      sameResource request past && past.action == "read" && past.kind == "success"))

def documents : PolicyPack := { name := "documents", rules := [
  permit "documents.tools" ["read", "write"],
  require "documents.read_before_write" ["write"] recentlyRead "read within one hour",
  require "documents.confirm" ["write"] confirmed "one-use, unrevoked user approval",
  require "documents.quota" ["write"] (quota 10 10000 3600) "principal dispatch budget",
  require "documents.single" ["read", "write"] singleFlight "serialize unresolved calls"
] }

end LeanGuard.Examples
