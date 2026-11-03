import LeanGuard.Domains.Retail
import LeanGuard.Domains.Airline
import LeanGuard.Domains.Telecom
import LeanGuard.ToolSchemas
import LeanGuard.DogwoodExamples
import LeanGuard.A2A

namespace LeanGuard
open Lean Data

def basePackFor : String → Except String PolicyPack
  | "retail" => .ok (withSchemas Domains.Retail.pack ToolSchemas.retail)
  | "airline" => .ok (withSchemas Domains.Airline.pack ToolSchemas.airline)
  | "telecom" => .ok (withSchemas Domains.Telecom.pack ToolSchemas.telecom)
  | "example" => .ok (withSchemas { name := "example", rules := [
      permit "example.tools" ["read", "write"],
      require "example.confirm" ["write"] confirmed "matching one-use confirmation",
      require "example.read_first" ["write"] (observed ["read"]) "read before write",
      require "example.quota" ["write"] (quota 10 10000 3600) "10 calls, 10000 units/hour",
      require "example.single" ["read", "write"] singleFlight "one in-flight call"
    ] } [("read", .object [] [("resource", .string)]),
      ("write", .object ["value"] [("value", .string), ("resource", .string),
        ("amount", .integer)])])
  | name => DogwoodExamples.packFor name

/-- Looks up a built-in pack. A `multiagent.` prefix adds the A2A operations to the base pack. -/
def packFor (name : String) : Except String PolicyPack := do
  if let some base := name.dropPrefix? "multiagent." then
    let pack ← basePackFor base.toString
    return { A2A.withOperations pack with name := name }
  basePackFor name

end LeanGuard
