# ALCF agent policy

A LeanGuard policy pack for agents that submit jobs on ALCF systems, plus the
adapter and glue needed to put it in front of the
[pbsMCP example](https://github.com/argonne-lcf/alcf-agentics-workflow/tree/main/pbsMCP)
in `alcf-agentics-workflow`. The rules come from the
[ALCF agent skillset](https://github.com/argonne-lcf/alcf-agent-skillset)'s
`agents/safety.md` and `agents/etiquette.md`. The design, including which rules
are not enforceable at a tool call, is in [docs/alcf-integration.md](../../docs/alcf-integration.md).

| File | What it is |
| --- | --- |
| `ALCF.lean` | The pack: thirteen permitted tools (eleven PBS, two in-process), ten requirements and one forbid |
| `ALCFMain.lean`, `ALCFAudit.lean` | The engine executable and the axiom audit |
| `pbs_adapter.py` | The adapter. Extracts facts (active jobs, node-minutes, script scan, resolved path) and fills PBS defaults |
| `guard.py` | `Guard`, the one call the agent loop makes; `ThresholdApprover`; `bridge`, `unwrap` and `qstat_from_mcp` for an MCP session |
| `fake_pbs.py`, `run.py` | Fake tools for the adapter, and the demo scenario, no PBS needed |
| `mcp_check/` | A fake `pbs_api` scheduler client for the real PBS MCP server, and a script that runs the patched pbsMCP loop against it |

## Run the demo

```sh
cd examples/alcf
mkdir -p .lake && ln -s ../../../.lake/packages .lake/packages   # reuse the main build's packages
lake update
lake build
../../.venv/bin/python run.py
```

Expected decisions, one per step:

```text
list queues            allowed  -
generate script        allowed  -
submit before qstat    denied   alcf.qstat_first, alcf.script_settled
list jobs              allowed  -
submit                 allowed  -
second debug submit    denied   alcf.debug_one, alcf.debug_spacing
oversized submit       denied   alcf.budget, alcf.approved
read token cache       denied   alcf.credentials
read job output        allowed  -
submit leaky script    denied   alcf.no_secrets
```

## Put it in front of pbsMCP

Install `mcp<2` in the pbsMCP venv. `pbs-mcp-demo` pins `mcp>=1.0.0` but
imports `mcp.server.fastmcp`, which mcp 2.x removed. Copy `pbs_adapter.py` and
`guard.py` next to `main.py`, then make four edits to `main.py`.

Imports:

```python
from pathlib import Path
from leanguard import GuardHost
from pbs_adapter import PBSAdapter
from guard import Guard, ThresholdApprover, bridge, qstat_from_mcp
```

In `run_agent`, after `await session.initialize()`:

```python
user = os.environ["USER"]
run_id = time.strftime("%Y%m%d-%H%M%S")
call_tool = bridge(session, asyncio.get_running_loop(), call_mcp_tool, CUSTOM_TOOLS)
adapter = PBSAdapter(call_tool=call_tool, qstat=qstat_from_mcp(call_tool, user))
host = GuardHost(
    "alcf",
    "alcf-journal.sqlite",
    adapter,
    binary=Path(".../alcf-guard"),
    principal=user,
    session=run_id,
)
guard = Guard(host, ThresholdApprover(max_node_minutes=480))
```

Give `run_conversation` a `guard` parameter, pass `guard` at both call sites
in `run_agent`, and replace the two dispatch branches with:

```python
payload = await guard.acall(tool_name, arguments)
```

At the end of the session block, write the trace and close the host:

```python
with open("alcf-events.jsonl", "w") as trace:
    for event in host.events():
        trace.write(json.dumps(event) + "\n")
host.close()
```

The agent sees `Tool call denied by policy.` and nothing else. Afterwards,

```sh
leanguard replay alcf alcf-events.jsonl --binary .../alcf-guard
```

prints each decision with its reasons. Build the engine on the login node:
Aurora is Linux x86-64.

`ThresholdApprover` approves every mutating call under the cap, which includes
`delete_job`, `hold_job` and `release_job`, since they cost no node-minutes. It
exists so the demo can run unattended. A deployment replaces it with a person.

The PBS server's tools return plain dicts, so the MCP SDK wraps each result as
`{"result": {...}}`. `bridge` unwraps that, so the adapter, `qstat_from_mcp`
and the agent all see the tool's own dict. Owners come back as `user@host`;
`qstat_from_mcp` filters on the part before the `@`.

## Check it against the Argonne code

```sh
pip install "mcp<2"   # for the PBS server; LeanGuard's own MCP server needs mcp 2
python examples/alcf/mcp_check/run.py /path/to/pbs-mcp-demo /path/to/alcf-agentics-workflow
```

This copies the pbsMCP loop, applies the edits above to its `main.py`, starts
the real PBS MCP server with `mcp_check/pbs_api.py` in place of the scheduler
client, and drives the loop with a fixed list of tool calls in place of the
model. It prints the decision table and exits non-zero if it differs from the
demo's. It has run on macOS against `pbs-mcp-demo` at e2a6291 and
`alcf-agentics-workflow` at 679d9da. Nothing has run against a PBS server.

## What the adapter trusts

The adapter lock covers this process only. Other users, and the same user's
own shell, can change the queue between the snapshot and the submit. The policy
sees the user's own unfinished jobs and the script as they were at decision
time. Read [docs/guarantees.md](../../docs/guarantees.md) before relying on it.
