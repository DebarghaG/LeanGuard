import LeanGuard.Runtime

namespace LeanGuard.Tests
open Formula

def event (id : String) (time : Nat) : Event :=
  { id := id, time := time, kind := "success", principal := "alice", session := "session",
    action := "read", resource := "document", binding := "" }

def atom (a : String) (h : History) : Bool := h.head?.any (fun e ↦ e.id == a)
def trace := [event "now" 100, event "approval" 90, event "old" 89]

#guard evaluate atom (.once (some 10) (.atom "approval")) trace
#guard !evaluate atom (.once (some 10) (.atom "old")) trace
#guard !evaluate atom (.previous none .top) []
#guard !evaluate atom (.previous none .top) [event "now" 100]
#guard evaluate atom (.since none (.neg (.atom "revoked")) (.atom "approval")) trace
#guard !evaluate atom (.since none (.neg (.atom "revoked")) (.atom "approval"))
  [event "now" 100, event "revoked" 95, event "approval" 90]
#guard !evaluate atom (.once (some 100) (.atom "future"))
  [event "now" 90, event "future" 100]
#guard !inWindow (some 100) [event "now" 90] [event "future" 100]
#guard evaluate atom (.within .conversation (.previous none (.atom "approval")))
  [event "now" 100, { event "foreign" 95 with session := "other" }, event "approval" 90]

def factless : α → History → Bool := fun _ _ ↦ true
def hardRules : List (Rule Unit) := [
  ⟨"permit", .permit, ["write"], .top, "test"⟩,
  ⟨"require", .require, ["write"], .bot, "test"⟩
]
#guard !authorize hardRules factless "write" trace
#guard !authorize ([] : List (Rule Unit)) factless "write" trace
#guard !combineExternal false (some true)
#guard !combineExternal true none
#guard combineExternal true (some true)

def large : Nat := 100000000000000000000000000000000000000000
#guard sumEvents [{ event "large" 100 with amount := large },
    { event "large2" 100 with amount := large }] (fun _ ↦ true) == 2 * large
#guard countEvents [event "repeat" 100, event "repeat" 100] (fun _ ↦ true) == 2

#guard Domains.Airline.canCancel ⟨100000, 13600, false, false, false, false, false⟩
#guard !Domains.Airline.canCancel ⟨100000, 13599, false, false, false, false, false⟩
#guard !Domains.Airline.canCancel ⟨100000, 100001, false, false, false, false, false⟩
#guard !Domains.Airline.canCancel ⟨100000, 99999, true, true, true, true, true⟩

def failing : Formula Check := check "missing" fun _ ↦ .error "missing trusted field"
def errorContext : Context := ⟨event "now" 100, .null, .null, [event "now" 100]⟩
def errorPack : PolicyPack := { name := "errors", rules := [permit "error" ["read"] (.top ⋎ failing)] }
#guard !(decidePolicy errorPack errorContext).allow
#guard !(decidePolicy { name := "errors", rules := [permit "negated_error" ["read"] (.neg failing)] }
  errorContext).allow

def scopeSensitive : Formula Check := check "projected_error" fun c ↦
  if c.history.length == 2 then .error "missing scoped fact" else .ok false
def scopeContext : Context := { errorContext with history :=
  [event "now" 100, { event "foreign" 95 with session := "other" }, event "old" 90] }
#guard !(decidePolicy { name := "errors", rules := [permit "projected" ["read"]
  (.neg (.within .conversation scopeSensitive))] } scopeContext).allow

def timedApproval (now : Nat) : Context :=
  let request := { event "request" now with kind := "request", action := "write", binding := "b" }
  ⟨request, .null, .null, [request,
    { event "confirmation" 0 with kind := "confirmed", action := "write", binding := "b" }]⟩

#guard evaluate (atomValue (timedApproval 3600)) (confirmedWithin 3600)
  (timedApproval 3600).history
#guard !evaluate (atomValue (timedApproval 3601)) (confirmedWithin 3600)
  (timedApproval 3601).history

def shiftedApproval : Context :=
  let c := timedApproval 10000
  { c with history := [c.request, event "recent_unrelated" 9900] ++ c.history.tail }
#guard !evaluate (atomValue shiftedApproval) (confirmedWithin 3600) shiftedApproval.history

end LeanGuard.Tests
