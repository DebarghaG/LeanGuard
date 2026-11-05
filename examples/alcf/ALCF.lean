import LeanGuard.Schema
import LeanGuard.Policy

/-!
# ALCF agent policy

Encodes the enforceable rules from the ALCF agent skillset
(`agents/safety.md` and `agents/etiquette.md`) for the PBS tool set used by the
`pbsMCP` example in `alcf-agentics-workflow`: the eleven tools of the PBS MCP
server plus the two in-process tools `generate_sim_script` and `read_local_file`.

The adapter (`pbs_adapter.py`) normalizes arguments before Lean sees them, so
`queue`, `node_count` and `walltime` are always present on a submit, and
`read_local_file` carries the resolved path. Every fact a rule reads is set on
every snapshot of that action; a missing fact is an evaluation error, and an
error denies the call.
-/

namespace ALCF
open LeanGuard Lean

def submits := ["submit_job"]
def scriptWriters :=
  ["generate_sim_script", "generate_aurora_pytorch_script", "generate_aurora_mpi_script"]
def jobControls := ["delete_job", "hold_job", "release_job"]
def queueReads := ["list_jobs", "get_job_status", "get_job_summary"]
def otherReads := ["list_queues", "list_nodes"]
def fileReads := ["read_local_file"]
def mutating := submits ++ scriptWriters ++ jobControls
def tools := mutating ++ queueReads ++ otherReads ++ fileReads

/-- Dispatches by this principal of one of `actions` strictly less than `window` seconds
before the request, counting only those whose normalized input satisfies `p`. This counts
dispatches, not completions: PBS finishes jobs asynchronously, so a dispatched submit is
the best evidence available at decision time. -/
def recentDispatches (actions : List String) (window : Nat) (p : Json → Bool) (c : Context) :
    Nat :=
  countEvents c.history fun e ↦
    samePrincipal c.request e && e.kind == "dispatch" && actions.contains e.action &&
    e.time ≤ c.request.time && c.request.time - e.time < window &&
    ((Json.parse e.inputJson).toOption.any p)

def anyInput (_ : Json) : Bool := true

/-- No dispatch of `actions` in the last `window` seconds. -/
def noRecentDispatch (actions : List String) (window : Nat) : Formula Check :=
  check "no_recent_dispatch" fun c ↦ .ok (recentDispatches actions window anyInput c == 0)

/-- Fewer than `n` dispatches of `actions` in the last `window` seconds. -/
def atMostDispatches (n : Nat) (actions : List String) (window : Nat) : Formula Check :=
  check "action_quota" fun c ↦ .ok (recentDispatches actions window anyInput c < n)

def isDebug (j : Json) : Bool := (Data.str j "queue").toOption == some "debug"
def singleNode (j : Json) : Bool := (Data.nat j "node_count").toOption.any (· ≤ 1)

/-- Etiquette: the debug queue allows one job per user. The adapter counts the user's
unfinished debug jobs from `qstat`. -/
def debugFree : Formula Check := check "debug_queue_free" fun c ↦ do
  if isDebug c.arguments then return (← Data.nat c.facts "debug_jobs_active") == 0
  return true

/-- Etiquette: wait at least 30 seconds between debug queue submissions. -/
def debugSpacing : Formula Check := check "debug_submission_spacing" fun c ↦
  .ok (!isDebug c.arguments || recentDispatches submits 30 isDebug c == 0)

/-- Safety: run a single-node job before a multi-node one. A single-node submit by the
same principal in the last day counts. -/
def testedFirst : Formula Check := check "single_node_first" fun c ↦
  .ok (singleNode c.arguments || recentDispatches submits 86400 singleNode c > 0)

/-- Safety: never put credentials in a job script. The adapter scans the script. -/
def noSecrets : Formula Check := check "no_secret_in_script" fun c ↦ do
  return !(← Data.bool c.facts "script_secret_pattern")

/-- Safety: the script must exist where the agent says it does. -/
def scriptPresent : Formula Check := check "script_exists" fun c ↦ Data.bool c.facts "script_exists"

/-- Safety: never read a token cache or key. The adapter resolves the path first. -/
def isCredential : Formula Check := check "credential_file" fun c ↦
  Data.bool c.facts "path_is_credential"

/-- Allocation: node-minutes of submits in the window, plus this one, stay under `minutes`. -/
def nodeMinuteBudget (minutes window : Nat) : Formula Check :=
  check "node_minute_budget" fun c ↦
    let matching := fun e ↦ samePrincipal c.request e && e.kind == "dispatch" &&
      submits.contains e.action && e.time ≤ c.request.time && c.request.time - e.time < window
    .ok (sumEvents c.history matching + c.request.amount ≤ minutes)

def pack : PolicyPack := withSchemas {
  name := "alcf"
  rules := [
    permit "alcf.tools" tools,
    require "alcf.qstat_first" submits (observed queueReads)
      "check queue status before submitting",
    require "alcf.debug_one" submits debugFree "debug queue allows one job per user",
    require "alcf.debug_spacing" submits debugSpacing "30 s between debug submissions",
    require "alcf.script_settled" submits (noRecentDispatch scriptWriters 3)
      "wait 3 s after writing a script before submitting it",
    require "alcf.submit_rate" submits (atMostDispatches 10 submits 3600)
      "at most ten submissions an hour",
    require "alcf.test_first" submits testedFirst "a single-node job before a multi-node one",
    require "alcf.script_exists" submits scriptPresent "the submit script must exist",
    require "alcf.no_secrets" submits noSecrets "no credentials in job scripts",
    require "alcf.budget" submits (nodeMinuteBudget 2880 86400) "48 node-hours a day",
    require "alcf.approved" mutating (confirmedWithin 600) "user approval within ten minutes",
    forbid "alcf.credentials" fileReads isCredential "never read a token cache or key"
  ]
} [
  ("submit_job", .object ["script_path", "queue", "node_count", "walltime"]
    [("script_path", .string), ("queue", .string), ("node_count", .integer),
     ("walltime", .string), ("account", .string), ("job_name", .string)]),
  ("delete_job", .object ["job_id"] [("job_id", .string), ("force", .boolean)]),
  ("hold_job", .object ["job_id"] [("job_id", .string)]),
  ("release_job", .object ["job_id"] [("job_id", .string)]),
  ("get_job_status", .object ["job_id"] [("job_id", .string), ("history", .boolean)]),
  ("list_jobs", .object [] [("job_id", .string), ("state_filter", .string),
    ("user_filter", .string), ("queue_filter", .string)]),
  ("get_job_summary", .object [] []),
  ("list_queues", .object [] []),
  ("list_nodes", .object [] [("state_filter", .string)]),
  ("generate_sim_script", .object [] [("protein", .string), ("steps", .integer)]),
  ("generate_aurora_pytorch_script", .object [] []),
  ("generate_aurora_mpi_script", .object [] []),
  ("read_local_file", .object ["path"] [("path", .string)])
]

end ALCF
