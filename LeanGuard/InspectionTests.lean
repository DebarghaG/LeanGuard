import LeanGuard.Inspection

namespace LeanGuard.InspectionTests
open Lean

-- Metadata cannot change a predicate's value or turn an input error into success.
example (ctx : Context) (c : Check) (info : Option Json) (h : History) :
    atomValue ctx { c with inspection := info } h = atomValue ctx c h := rfl

example (ctx : Context) (c : Check) (info : Option Json) (h : History) :
    evaluationErrors ctx (.atom { c with inspection := info }) h =
      evaluationErrors ctx (.atom c) h := rfl

def custom := check "dispatch_quota" fun _ ↦ .error "opaque custom predicate"
#guard (inspectFormula custom).getObjValAs? Bool "opaque" == .ok true
#guard (inspectFormula (quota 3 17 60)).getObjValAs? Bool "opaque" == .ok false
#guard ((inspectFormula (quota 3 17 60)).getObjVal? "description" >>= fun j ↦
  j.getObjValAs? Nat "amount") == .ok 17

def request : Event := {
  id := "r", time := 100, kind := "request", principal := "p", session := "s",
  action := "write", resource := "document", binding := "binding", amount := 17 }
def context : Context := ⟨request, .null, .null, [request]⟩
#guard evaluate (atomValue context) (quota 3 17 60) context.history
#guard !evaluate (atomValue context) (quota 3 16 60) context.history

def allConstructors : Formula Check :=
  .within .workflow (.since (some 5) (.conj (.neg .bot) (.previous none .top))
    (.disj (.once (some 0) custom) (quota 3 17 60)))

#guard (inspectFormula allConstructors).getObjValAs? String "op" == .ok "within"
#guard ((inspectFormula allConstructors).getObjVal? "child" >>= fun j ↦
  j.getObjValAs? String "op") == .ok "since"

end LeanGuard.InspectionTests
