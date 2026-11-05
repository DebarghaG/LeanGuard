# Integrating LeanGuard with the ALCF agent repositories

Design notes, November 2026. Part 1 is now implemented in
[`examples/alcf`](../examples/alcf/README.md): the pack, the adapter, the guard
for the pbsMCP loop, a fake scheduler, and tests. The Lean snippets below are the
original sketches; the example is the reference. Parts 2 and 3 are design only. The
scoping that preceded this document recommended three steps in order: an
`alcf` policy pack fed by the skillset rules together with a guarded pbsMCP
demo, then ChemGraph, with LAMMPS-Agents parked. This document is the "how"
for each.

Repositories studied, all at their default branch on 2026-11-04:

| Repository | What it is | Where LeanGuard sits |
| --- | --- | --- |
| [alcf-agent-skillset](https://github.com/argonne-lcf/alcf-agent-skillset) | Markdown skills. `agents/safety.md` and `agents/etiquette.md` hold the rules. | Source of the policy pack. No code integration. |
| [alcf-agentics-workflow](https://github.com/argonne-lcf/alcf-agentics-workflow), `pbsMCP/` | OpenAI-SDK tool loop on an Aurora login node, calling the external [pbs-mcp-demo](https://github.com/jtchilders/pbs-mcp-demo) server plus two in-process tools. | A `GuardHost` inside the loop. |
| [ChemGraph](https://github.com/argonne-lcf/ChemGraph) | LangGraph agent with its own "scoped runtime" (prepare, digest, journal, approve, execute) and an IRI Facility API client. | Decision engine behind the scoped runtime's authorizer. Needs a new LeanGuard host mode. |
| [LAMMPS-Agents](https://github.com/ANL-NST/LAMMPS-Agents) | AutoGen 0.4 dev, hardcoded `scp` to one host, HPC paths mostly commented out. | Parked. |

None of the four mentions LeanGuard today. ChemGraph's runtime is convergent
design by another author, not something built for LeanGuard.

## Part 1: the `alcf` policy pack and the pbsMCP demo

### 1.1 What the pbsMCP loop does today

`pbsMCP/src/main.py` builds an OpenAI client against the Sophia inference
service, starts `python -m pbs_mcp.server` over stdio, lists its eleven tools,
appends two in-process tools from `tools/custom_tools.py`, and runs a manual
conversation loop. In `run_conversation`, each tool call takes one of two
branches:

```python
if tool_name in CUSTOM_TOOLS:
    payload = CUSTOM_TOOLS[tool_name](arguments)          # in-process Python
else:
    payload = await call_mcp_tool(session, tool_name, arguments)  # PBS MCP server
```

The tools that matter for policy:

| Tool | Source | Effect | Arguments the policy cares about |
| --- | --- | --- | --- |
| `submit_job` | pbs_mcp | Mutating. `qsub`. | `script_path`, `queue` (default `debug`), `walltime` (`HH:MM:SS`, default `00:10:00`), `node_count` (default 1), `account` |
| `delete_job`, `hold_job`, `release_job` | pbs_mcp | Mutating. | `job_id`, `force` |
| `get_job_status`, `list_jobs`, `get_job_summary`, `list_queues`, `list_nodes` | pbs_mcp | Read-only. | `job_id` |
| `generate_aurora_pytorch_script` | pbs_mcp | Writes a script file. | paths |
| `generate_sim_script` | in-process | Writes `submit_openmm.sh` and `params.json` in the example directory. | `protein`, `steps` |
| `read_local_file` | in-process | Reads up to 16 KB from any absolute path. | `path` |

Two facts shape the integration. First, the choke point is the loop, not the
MCP server. A proxy in front of `pbs_mcp` never sees `generate_sim_script` or
`read_local_file`. Second, `read_local_file` accepts any absolute path, and
`safety.md` names the Globus token cache under `~/.globus/` as a credential to
protect. That is a concrete `forbid` rule and a good demo moment: the agent is
told to read the token file and the policy refuses before the file is opened.

### 1.2 Wiring: one guarded call for both branches

Replace the two branches with one call into a `GuardHost` whose adapter owns
both dispatch paths.

```python
# pseudocode
class PBSAdapter:
    """Adapter contract from python/leanguard/host.py: snapshot, execute, lock."""

    def __init__(self, session, loop, user):
        self.session, self.loop, self.user = session, loop, user
        self.lock = threading.RLock()

    def execute(self, action, arguments):
        if action in CUSTOM_TOOLS:
            return CUSTOM_TOOLS[action](json.dumps(arguments))
        future = asyncio.run_coroutine_threadsafe(
            call_mcp_tool(self.session, action, json.dumps(arguments)), self.loop)
        return future.result()   # the example unwraps FastMCP's {"result": ...} here

    def snapshot(self, action, arguments, customer):
        ...  # section 1.3

    def mutating(self, action):
        return action in {"submit_job", "delete_job", "hold_job", "release_job",
                          "generate_sim_script", "generate_aurora_pytorch_script"}
```

In `run_conversation`, the dispatch becomes:

```python
payload = await asyncio.to_thread(guarded, host, tool_name, arguments)
```

where `guarded` prepares and confirms a proposal when `host.adapter.mutating`
says so, then calls `host.execute`. The approval function is discussed in 1.6.

Why this shape and not the alternatives:

- `GuardHost.execute` is synchronous and holds a threading lock while the
  adapter runs. The loop and the MCP session are async. Running the host call in
  a worker thread and letting the adapter call back into the running loop with
  `run_coroutine_threadsafe` is the smallest change that avoids a deadlock.
- The adapter could call the `pbs_api` Python package directly instead of going
  through the PBS MCP server. That removes a process but changes what the demo
  shows. The demo exists to show MCP on ALCF, so keep the server and go through
  it.
- A LeanGuard MCP proxy in front of `pbs_mcp` would leave the in-process tools
  unguarded. It is the right shape for `mace-mcp-server` (Part 3), not for this
  loop.

Version note: `pbs-mcp-demo` pins `mcp>=1.0.0` but imports
`mcp.server.fastmcp`, which mcp 2.x removed, so its venv needs `mcp<2`.
LeanGuard's MCP module targets mcp 2.x. This does not matter here, because
`GuardHost` and the adapter use no MCP code; the loop keeps its own `mcp`
version. It would matter if a LeanGuard MCP proxy were put in the chain, which
would then need its own virtual environment. Two facts checked against the real
server with a fake `pbs_api`: the server's tools return plain dicts, so the SDK
puts each result under a `result` key in `structuredContent`, and PBS owners
come back as `user@host`. The example's `bridge` and `qstat_from_mcp` handle
both.

### 1.3 The adapter's snapshot: facts, revision, amount

Most of the work is in `snapshot`, not the wiring. LeanGuard trusts the
adapter to extract authoritative facts with exact units and to hold a lock that
every writer respects (see [guarantees](guarantees.md), "What you have to
trust"). On a shared scheduler the lock covers only this process. It cannot
cover other users, or the same user's own shell. State that in the demo.

Resource convention: every PBS tool reports the same resource string, for
example `pbs:aurora`. `observed` requires `sameResource` and the same
conversation, so if `submit_job` and `list_jobs` reported different resources
the "qstat before qsub" rule would never fire. The in-process file tools use
`file:<absolute path>`, which means a rule on `submit_job` cannot use
`observed` to ask about file reads; it has to use the action-filtered check
from 1.5 instead.

Facts to extract, by action:

| Fact | Computed from | Used by rules |
| --- | --- | --- |
| `user_jobs_active` | `qstat -u $USER` (via `list_jobs` on the session, or `pbs_api` directly) | too many jobs |
| `debug_jobs_active` | same, filtered to `queue == debug` and state in `Q`, `R`, `H` | one debug job per user |
| `node_minutes` | `node_count × walltime` in whole minutes; becomes the event `amount` | allocation budget, small test first, approval threshold |
| `script_digest` | SHA-256 of the file at `script_path` | revision, retry rule |
| `script_secret_pattern` | regex over the script: `export *_KEY=`, `TOKEN=`, `Bearer `, Globus client secrets | no credentials in job scripts |
| `script_under_home` | path is under the user's home or project directory | sanity |
| `path_is_credential` | for `read_local_file`: path under `~/.globus/`, `~/.ssh/`, or matching `tokens.json` | protect credentials |
| `last_job_for_script` | state and `Exit_status` of the most recent job whose `Job_Name` or script matched, from `qstat -x` history | no blind retry |
| `allocation_balance` | `sbank`, once a tool for it exists; until then the balance rule is left out of the pack | check balance before large jobs |

The example implements `debug_jobs_active`, `node_minutes`, `script_exists`,
`script_digest`, `script_secret_pattern` and `path_is_credential`. The other
rows are candidates for later.

Every fact a rule reads must be one the adapter always sets for that action.
A check that reads a missing fact errors, and an error counts as a refusal, so
an optional fact would refuse every call on a machine that lacks it.

Revision: hash only what the rules depend on. Hashing the whole queue would
make every approval stale on a busy scheduler, because `confirm` and `execute`
both re-snapshot and compare revisions. Hash the user's own active job list
(ids and states) plus `script_digest`. An approval then survives other users'
activity but not the user's own script changing under it.

Amount: `node_minutes` for `submit_job`, zero otherwise. This is what turns
allocation protection into arithmetic. `quota calls amount window` sums
`amount` over dispatches, and with `MultiAgentHost` a grant's `amount` caps a
workflow's node-minutes across every agent in it.

### 1.4 Rule table

Rules from `agents/safety.md` and `agents/etiquette.md`, mapped to what
LeanGuard can check at a tool call. "History" means the rule is decided from
journaled events; "snapshot" means from facts the adapter extracted now.

| Rule (source) | Applies to | LeanGuard construct | Source of truth | Status |
| --- | --- | --- | --- | --- |
| Check queue status before submitting (etiquette) | `submit_job` | `require ... (observed ["list_jobs", "get_job_status", "get_job_summary"])` | history | existing |
| Debug queue: one job per user (etiquette) | `submit_job` with `queue == debug` | `forbid` when fact `debug_jobs_active ≥ 1` | snapshot | existing, needs fact |
| Not too many jobs without reviewing the queue (etiquette) | `submit_job` | action-filtered count of submits in the last hour, plus `observed` of a queue read | history | needs small new check (1.5) |
| 30 s between debug submissions (etiquette, IRI) | `submit_job` with `queue == debug` | `neg` of an action-filtered dispatch within 30 s | history | needs small new check |
| 3 s between writing a script and running it (etiquette, IRI) | `submit_job` | no `generate_*` success within the last 3 s on the same resource | history | needs small new check |
| Check quota before large writes (safety, etiquette) | `generate_*`, and any future write tool | `observed ["check_quota"]` when a size fact exceeds a threshold | history + snapshot | needs a quota tool first; not in pbs_mcp today |
| No credentials in job scripts (safety) | `submit_job` | `forbid` when `script_secret_pattern` | snapshot | existing, needs fact; heuristic |
| Protect the token cache (safety) | `read_local_file` | `forbid` when `path_is_credential` | snapshot | existing, needs fact |
| Check balance before large jobs (safety) | `submit_job` with `node_minutes > threshold` | `observed ["check_balance"]` | history | needs an `sbank` tool; absent today |
| Small test job before scaling (safety) | `submit_job` with `node_count > 1` | `once` over history for a successful submit with `node_count ≤ 1`, parsing `inputJson` | history | needs small new check |
| Do not retry a failed job without investigating (safety) | `submit_job` | if `last_job_for_script` failed, require a `read_local_file` dispatch since then whose `path` equals the `stderr_path` fact, via `recentDispatches` with an input predicate; `observed` cannot be used because the file tools report a different resource | snapshot + history | feasible, moderate; needs the new check and a time fact |
| Allocation is finite (safety) | `submit_job` | `quota` on `amount` per hour or per workflow grant | history | existing |
| Human approval for mutating actions (safety, "ask first") | all mutating | `confirmed` or `confirmedWithin` | history | existing |
| Never `rm -rf` unowned dirs, never touch `/soft`, `/opt` (safety) | a shell tool | argument parse plus ownership facts | snapshot | no shell tool in pbsMCP; applies to ChemGraph and skillset `remote-bash` |
| SIGINT before `kill -9` (etiquette) | a shell tool | `forbid kill -9` unless a prior `kill -2` on the same pid was observed | history | no shell tool here |
| No heavy work on login nodes (etiquette) | a shell tool | not a property of a call; a forbid list of known heavy commands is a heuristic at best | n/a | not enforceable |
| No persistent background processes (etiquette) | a shell tool | same | n/a | not enforceable |
| Verify output before declaring success (etiquette) | model text | not a tool call; the retry rule above is the closest tool-level stand-in | partial | partial |
| Checkpointing for long jobs (etiquette) | script content | not checkable | n/a | not enforceable |
| Never print credentials (safety) | runtime behaviour | not checkable | n/a | not enforceable |

Roughly half of the rules map directly, a third need facts the adapter can
compute, and the rest are about process behaviour that no tool-call guard can
see. The honest pitch to Argonne is the first two groups.

### 1.5 One generic addition to the DSL

`quota` counts every dispatch by the principal in the window, reads included.
Three rules above need "dispatches of these actions, with this argument, in the
last N seconds". Rather than ALCF-specific code, add one generic check to
`LeanGuard/Policy.lean`:

```lean
-- Sketch, not compiled.
/-- Dispatches by this principal of one of `actions` in the last `window` seconds,
    counting only events whose input satisfies `p`. -/
def recentDispatches (actions : List String) (window : Nat) (p : Json → Bool := fun _ ↦ true)
    (c : Context) : Nat :=
  countEvents c.history fun e ↦
    samePrincipal c.request e && e.kind == "dispatch" && actions.contains e.action &&
    e.time ≤ c.request.time && c.request.time - e.time ≤ window &&
    ((Json.parse e.inputJson).toOption.any p)

def noRecentDispatch (actions : List String) (window : Nat) (p : Json → Bool := fun _ ↦ true) :
    Formula Check := check "no_recent_dispatch" fun c ↦ .ok (recentDispatches actions window p c == 0)

def atMostDispatches (n : Nat) (actions : List String) (window : Nat) : Formula Check :=
  check "action_quota" fun c ↦ .ok (recentDispatches actions window (fun _ ↦ true) c < n)
```

`Json.parse e.inputJson` is already used this way in `A2A.lean`, `Query.lean`
and `Replay.lean`, so parsing past inputs inside a check is established
practice. This covers the 30 s rule, the 3 s rule, the per-hour submit count
and, with a predicate on `node_count`, the "small test job first" rule.

### 1.6 The pack

Sketch of `alcf` for the pbsMCP tool set. Not compiled.

```lean
import LeanGuard.Schema
import LeanGuard.Policy

namespace ALCF
open LeanGuard

def submits := ["submit_job"]
def mutating := ["submit_job", "delete_job", "hold_job", "release_job",
                 "generate_sim_script", "generate_aurora_pytorch_script"]
def queueReads := ["list_jobs", "get_job_status", "get_job_summary"]

def isDebug (j : Json) : Bool := (Data.str j "queue").toOption == some "debug"
def smallJob (j : Json) : Bool := (Data.nat j "node_count").toOption.any (· ≤ 1)

def debugFree : Formula Check := check "debug_queue_free" fun c ↦ do
  if isDebug c.arguments then return (← Data.nat c.facts "debug_jobs_active") == 0 else return true

def noSecrets : Formula Check := check "no_secret_in_script" fun c ↦ do
  return !(← Data.bool c.facts "script_secret_pattern")

def notCredential : Formula Check := check "not_a_credential_file" fun c ↦ do
  return !(← Data.bool c.facts "path_is_credential")

def testedFirst : Formula Check := check "small_job_first" fun c ↦ do
  if smallJob c.arguments then return true
  return recentDispatches submits 86400 smallJob c > 0

def pack : PolicyPack := withSchemas {
  name := "alcf"
  rules := [
    permit "alcf.tools" (mutating ++ queueReads ++ ["list_queues", "list_nodes", "read_local_file"]),
    require "alcf.qstat_first" submits (observed queueReads) "check queue status before submitting",
    require "alcf.debug_one" submits debugFree "debug queue allows one job per user",
    require "alcf.debug_spacing" submits (noRecentDispatch submits 30 isDebug) "30 s between debug submissions",
    require "alcf.script_settled" submits (noRecentDispatch ["generate_sim_script", "generate_aurora_pytorch_script"] 3) "let the script sync",
    require "alcf.submit_rate" submits (atMostDispatches 10 submits 3600) "at most ten submits an hour",
    require "alcf.test_first" submits testedFirst "a single-node job before a multi-node one",
    require "alcf.no_secrets" submits noSecrets "no credentials in job scripts",
    require "alcf.budget" submits (quota 1000 2880 86400) "48 node-hours a day",
    require "alcf.approved" mutating (confirmedWithin 600) "user approval within ten minutes",
    forbid "alcf.credentials" ["read_local_file"] (.neg notCredential) "never read a token cache"
  ]
} [("submit_job", .object ["script_path"] [("script_path", .string), ("queue", .string),
      ("walltime", .string), ("node_count", .integer), ("account", .string)]),
   ("read_local_file", .object ["path"] [("path", .string)]),
   -- remaining tools omitted in the sketch
  ]

end ALCF
```

Notes on the sketch:

- `forbid` with `.neg` reads oddly; `forbid` holds when its formula is true, so
  the formula is "the path is a credential". Writing it as a `require` with
  `notCredential` is equivalent and clearer. Pick one style for the pack.
- The budget numbers are placeholders. 2880 node-minutes is 48 node-hours.
- The proof worth stating is the budget one: every admitted `submit_job`
  carries `node_minutes` such that the window sum stays under the cap. That is
  the same shape as the `custom_policy` example's budget proof.

Where the pack lives is a decision. `Builtins.basePackFor` is a hard-coded name
match, so an `alcf` built-in means editing `Builtins.lean` and shipping ALCF
rules in every LeanGuard wheel. The alternative is a downstream Lake package in
the style of `examples/custom_policy`, built on the login node, with its own
proof and audit. The downstream package is the better fit: Argonne owns the
rules and the numbers, and the skillset repository can point at it. The cost is
a Lake build on Aurora, which the tutorials already walk through.

### 1.7 Approval in a headless run

The pbsMCP demo is non-interactive. `approve(proposal)` has to do something
without a user at a screen. Three options:

1. Terminal prompt. The operator running `main.py` answers `y` or `n`. Shows
   the real thing, breaks unattended runs.
2. Threshold. Auto-approve below a `node_minutes` cutoff, deny above. Keeps the
   demo unattended and still shows a refusal when the agent asks for too much.
3. Always approve, and let the other rules do the work, as Tutorial 6 does.

Option 2 is the one to show Argonne, with the cutoff printed in the log. The
approval function must stay in `main.py`, never exposed as a tool.

### 1.8 What the demo would show

Run on an Aurora login node, which is Linux x86-64 and therefore a supported
engine platform. Default prompt unchanged. Expected sequence: `list_queues`
allowed; `generate_sim_script` allowed after approval; `submit_job` refused
once with `alcf.qstat_first` because the agent never listed jobs; the agent
calls `list_jobs`; `submit_job` allowed; a second `submit_job` to debug refused
with `alcf.debug_one` and `alcf.debug_spacing`; `read_local_file` on the token
cache refused with `alcf.credentials`. Then `leanguard replay` over the
exported trace shows every decision and the rules behind it.

Effort: the adapter's facts are the bulk of it. The qstat and script parsing is
a day or two; the DSL addition and the pack another day or two; the proof and
audit depend on how far Argonne wants to take it.

## Part 2: ChemGraph

### 2.1 What exists

ChemGraph's scoped runtime, in `src/chemgraph/runtime/`, already has the LeanGuard
shape: `prepare` builds a `PreparedAction` with a digest, `OperationJournal`
drives a record through proposed, approved, invoking, returned and finalized
states in an `OperationStore` (compare-and-set `put`), `ScopedToolsMiddleware`
interrupts the LangGraph run for approval, and `default_authorizer(record)`
checks for an unexpired approval of exactly the prepared digest. The docs say
the embedding service owns authentication and decisions.

Separately, `tools/alcf_iri_core.py` refuses `submit_job`, `update_job` and
`cancel_job` against the IRI Facility API unless `ALCF_IRI_ALLOW_UNSAFE=1` is
set, with the message "Ship HITL first (planned)".

### 2.2 Why `GuardHost` does not fit as is

Two facts change the shape:

- `OperationJournal.authorizer` only validates an existing approval. The
  deny-before-propose step is `ExecutionPolicy` inside `prepare`. So the seam is
  two callables, not one.
- ChemGraph's middleware runs the tool. `GuardHost` assumes it owns dispatch:
  `execute` snapshots, asks Lean, runs the adapter, and journals the outcome
  under one lock. Handing ChemGraph a `GuardHost` would mean two journals, two
  digests and two executors.

What fits is a decision-only host built on `Engine.request` with the `admit`
and `observe` operations that `GuardHost._record` already sends. The embedder
calls `admit` with the event, arguments and facts; if allowed, the embedder
runs the tool and reports `success`, `failure` or `unknown` through `observe`.
LeanGuard keeps its journal and replay; ChemGraph keeps its store and
middleware. This "embedded" or "decision" host is the LeanGuard prerequisite
for ChemGraph, and it is a generic piece: any runtime that already owns
execution would use it.

### 2.3 Mapping

| ChemGraph | LeanGuard |
| --- | --- |
| `context.owner` | principal |
| `context.thread_id` | session |
| `context.task_id` | workflow |
| `PreparedAction.digest` | the proposal's canonical arguments plus revision |
| `OperationJournal.decide(approve=True)` | `confirm` event |
| record state `invoking` | `dispatch` event |
| record state `returned` | `success` or `unknown` outcome |

`ExecutionPolicy` becomes a thin call to `admit` for the permit and forbid
rules; `authorizer` becomes a second `admit` that includes the `confirmed`
requirement. Or, simpler, one `admit` at authorize time with the whole pack,
and `ExecutionPolicy` kept only for its argument normalization.

### 2.4 The IRI gate

`_check_unsafe` is an environment-variable switch around three write actions.
With the decision host in place it becomes a `confirmedWithin` requirement on
`alcf_compute` with `action in {submit_job, update_job, cancel_job}`, with
`amount` computed from the jobspec (`resources.node_count × attributes.duration`
in minutes) so the same budget rule from Part 1 applies. The tool description
that tells the model "do NOT refuse preemptively" stays; the refusal just moves
from a `RuntimeError` to a policy decision the journal can explain.

### 2.5 Dependencies

ChemGraph pins `langgraph==1.2.16`, `langchain==1.4.0` and `mcp==1.28.1`.
LeanGuard's core package has no third-party dependencies, so the pin wall only
bites the `mcp` extra, which ChemGraph would not install. The engine binary is
Linux-only, which matches where ChemGraph runs against IRI.

### 2.6 What to ask Argonne

- Who owns the decision: LeanGuard behind `authorizer`, or LeanGuard replacing
  `ExecutionPolicy` and `authorizer` both. Our recommendation is the latter,
  with ChemGraph's store kept as the operational record and LeanGuard's journal
  as the evidence record.
- Whether the IRI gate should become policy now or wait for their planned HITL.
- Which ChemGraph tools beyond IRI are "scoped" today, so the pack covers them.

This is a conversation before it is code. Open it with this document's Part 2
and the pbsMCP demo running.

## Part 3: the rest

### 3.1 mace-mcp-server

`alcf-agentics-workflow/mace-mcp-server/src/server.py` is a FastMCP server with
a handful of tools and no in-process side channel. This is where a generic
LeanGuard MCP proxy fits: one process that connects to an upstream stdio
server, mirrors its tool list, and routes each call through a `GuardHost`
whose adapter forwards to the upstream session. The proxy runs in its own
virtual environment on mcp 2.x and speaks the protocol to the 1.x upstream.
LeanGuard does not have this proxy today; `mcp_server.py` exposes only
`guarded_call`. Building it is a few hundred lines and reusable for ChemGraph's
own MCP servers. It is the second LeanGuard prerequisite, after the decision
host, and lower priority.

### 3.2 LAMMPS-Agents

Parked, as scoped. The interception point exists in `register_function`, but
the code pins an AutoGen development release, hardcodes an `scp` target, has
most HPC paths commented out, sets human input to never, and last changed a
year ago. If Argonne asks for it, the same adapter pattern as Part 1 applies
to its `lmp` and `scp` calls, with the shell rules from the table (no `rm -rf`
on unowned paths, protected directories) as the pack.

## Decisions

Taken in the implementation: the `alcf` pack is a downstream Lake package under
`examples/alcf`, and the headless demo approves by a node-minute threshold. The
action-filtered recent-dispatch check lives in the example's Lean file, not in
`Policy.lean`, so Argonne needs no new LeanGuard release; it can move into the
library later.

Still open:

1. Whether to build the decision-only host before or after the pbsMCP demo runs
   on a real system. It is not needed for the demo. It is needed for ChemGraph.
2. Whether to open the ChemGraph conversation with Argonne now, in parallel
   with the demo, or after it runs.
