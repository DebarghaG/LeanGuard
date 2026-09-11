import LeanGuard.Experimental.Repair
import LeanGuard.Builtins

/-!
# Repair contracts used by the saved-rollout experiment

Lookup repairs retain facts and past events and target the recorded customer.
Document plans model the existing synthetic training fixture before execution:
admitted calls succeed, each call advances time by one second, and initial
observations and approval are supplied by the trusted fixture.
-/

namespace LeanGuard.Experimental
open Lean

/-- The complete built-in decision, including schemas and the error gate. -/
def accepted (domain : String) (ctx : Context) : Bool :=
  match packFor domain with
  | .ok pack => (decidePolicy pack ctx).allow
  | .error _ => false

/-- A read-only customer lookup repair. Only the ID, resource, and input encoding change. -/
def lookupContext (ctx : Context) (customer : String) : Context :=
  let arguments := Json.mkObj [("user_id", .str customer)]
  let request := { ctx.request with resource := customer, inputJson := arguments.compress }
  { ctx with request := request, arguments := arguments, history := request :: ctx.history.tail }

/-- Require the replacement ID to equal the identity already present in the snapshot. -/
def lookupRepair (ctx : Context) (customer : String) : Prop :=
  (Data.str ctx.facts "customer_id").toOption = some customer ∧
    ctx.request.action = "get_user_details" ∧ accepted "airline" (lookupContext ctx customer) = true

instance (ctx : Context) (customer : String) : Decidable (lookupRepair ctx customer) :=
  inferInstanceAs (Decidable (_ ∧ _ ∧ _))

structure DocumentCall where
  action : String
  resource : String
  value : String := ""
  binding : String := ""
  deriving Repr, DecidableEq

def DocumentCall.arguments (call : DocumentCall) : Json :=
  if call.action == "write" then
    Json.mkObj [("resource", .str call.resource), ("value", .str call.value)]
  else Json.mkObj [("resource", .str call.resource)]

/-- Fix the requested write and approval; these values come from the original task fixture. -/
structure DocumentTask where
  session : String
  target : String
  value : String
  resources : List String
  approvedBinding : String

/-- Check every admission and final task completion in the deterministic document fixture.
This cannot remove any event from `past`. It can change only not-yet-executed calls.
The premise that admitted reads/writes succeed is specific to this synthetic fixture. -/
def documentPlanSafe (task : DocumentTask) (past : History)
    (calls : List DocumentCall) (index : Nat := 0) (done : Bool := false) : Bool :=
  match calls with
  | [] => done
  | call :: rest =>
    let arguments := call.arguments
    let request : Event := {
      id := s!"call-{index}", time := 1000 + index, kind := "request",
      principal := "sandbox-user", session := task.session, action := call.action,
      resource := call.resource, binding := call.binding, inputJson := arguments.compress
    }
    let ctx : Context := ⟨request, arguments, Json.mkObj [], request :: past⟩
    let intent := task.resources.contains call.resource &&
      (call.action == "read" || (call.action == "write" && call.resource == task.target &&
        call.value == task.value && call.binding == task.approvedBinding))
    let done := if call.action == "write" then true else done
    intent && accepted "example" ctx && documentPlanSafe task
      ({ request with kind := "success" } :: { request with kind := "dispatch" } ::
        request :: past) rest (index + 1) done

end LeanGuard.Experimental
