import LeanGuard.Runtime

namespace LeanGuard.Replay
open Lean Data

/-- Offline trace fragments may begin with responses whose requests predate the fragment.
This evaluator cannot dispatch tools and does not relax the live outcome protocol. -/
def run (pack : PolicyPack) (events : List Event) : Except String (Array Json) := do
  validatePack pack
  let mut history : History := []
  let mut decisions : Array Json := #[]
  for original in events do
    let e := if original.kind == "response" then { original with kind := "success" } else original
    if history.head?.any (fun previous ↦ e.time < previous.time) then
      throw "trace timestamps moved backwards"
    if !["request", "dispatch", "success", "failure", "unknown", "confirmed", "revoked",
        "identity", "user_observation"].contains e.kind then throw "unknown replay event kind"
    history := e :: history
    if e.kind == "request" then
      let arguments ← Json.parse e.inputJson
      let ctx : Context := ⟨e, arguments, .null, history⟩
      let decision := decidePolicy pack ctx
      decisions := decisions.push (Json.mkObj [
        ("id", toJson e.id), ("time", toJson e.time), ("decision", toJson decision)])
  return decisions

def handle (input : Json) : Except String Json := do
  let scenario ← str input "scenario"
  let pack ← if scenario == "dogwood.unsafe_response_sum" then
      pure DogwoodExamples.unsafeResponseSum else DogwoodExamples.packFor scenario
  let events ← (← array input "events").toList.mapM eventFromJson
  return Json.mkObj [("scenario", toJson scenario), ("decisions", toJson (← run pack events))]

end LeanGuard.Replay
