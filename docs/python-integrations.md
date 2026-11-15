# Python framework tools

LeanGuard supplies a `guarded_tool(host)` factory in each optional
`leanguard.integrations.<framework>` module. Each factory registers one
`guarded_call` tool with `action`, `arguments`, and optional `proposal_id` inputs.
It delegates the full operation to the host's existing backend adapter; it does
not wrap arbitrary framework tools or infer backend facts from their output.

```sh
pip install 'leanguard[agent-strands]'
```

```python
from pathlib import Path
from leanguard import GuardHost
from leanguard.demo import MemoryTools
from leanguard.integrations.strands import guarded_tool
from strands import Agent

with GuardHost("example", Path("private/events.sqlite"), MemoryTools(),
               principal="alice", session="conversation-1") as host:
    agent = Agent(tools=[guarded_tool(host)])
    # Configure your model/provider before invoking the agent.
    # Keep the host open until the agent and all tool work have finished.
```

Replace `MemoryTools` with an authoritative backend adapter in production. Its
lock must coordinate every writer. Never register the underlying raw tools or
give the agent another credential/path to the same backend.

| Module / extra suffix | SDK registration type | Invocation coverage |
| --- | --- | --- |
| `strands` | decorated Strands tool | async tool stream |
| `langchain` | `StructuredTool` | sync/async tool; LangGraph `ToolNode` |
| `deepagents` | same LangChain tool | Deep Agents graph with deterministic model |
| `openai` | `FunctionTool` | function invocation; hosted tools excluded |
| `adk` | `FunctionTool` | async invocation |
| `microsoft` | `FunctionTool` | Python invocation; .NET not included |
| `crewai` | CrewAI tool | synchronous invocation, cache disabled |
| `llamaindex` | `FunctionTool` | call/acall |
| `pydantic` | `Tool` | toolset execution, no framework retry allowance |
| `agno` | `Function` | async `FunctionCall` |
| `haystack` | `Tool` | invoke/invoke_async on Haystack 3 |
| `smolagents` | `Tool` | synchronous tool invocation |
| `dspy` | `Tool` | async tool invocation |
| `camel` | `FunctionTool` | async tool invocation |
| `claude` | SDK MCP tool | in-process MCP request/response |

Install `agent-<suffix>` and import the corresponding module. All SDK imports
are lazy, so the core package remains dependency-free. Exact tested versions
live in `pyproject.toml`; they deliberately describe a narrow support set.
Use isolated environments when frameworks have incompatible dependencies.
In particular, CAMEL's current stable release needs MCP 1.x and cannot share an
environment with LeanGuard's MCP 2.x server extra; its native tool integration
does not need that server. Do not force conflicting dependency versions.

Claude Agent SDK uses `create_sdk_mcp_server("leanguard", tools=[guarded_tool(host)])`
and `ClaudeAgentOptions(mcp_servers={"leanguard": server},
allowed_tools=["mcp__leanguard__guarded_call"])`. Its built-in tools and permission
modes remain separate controls; the approval authority is still the host UI.

## Authority and outcomes

Only trusted application code owns the host. Approval uses `host.prepare`, an
authenticated human review of the exact proposal details, and `host.confirm`.
The model may pass an existing proposal ID; that reference does not grant approval.
Framework approval flags, context objects, and tool output do not create trusted
identity or confirmations. A changed or consumed proposal remains denied.

The model sees denial/status/request correlation and successful backend results.
Detailed rules, evidence, and exception text stay in the trusted journal. An
allowed call can have an `unknown` outcome: it might have taken effect. These
factories never retry it. Configure surrounding SDK retry/caching middleware so
it cannot bypass the host or turn an uncertain result into a successful one.

Host exceptions become a generic `GuardedCallError` because SDKs may place their
text in model-visible tool messages. It does not claim denial or absence of
effects; trusted Python callers can inspect its original exception context.
The MCP server uses this same result/error boundary, including removal of the
private `error` field from recorded failure/unknown results. Do not depend on
that diagnostic field in model-facing code.

Async factories run the complete synchronous host transaction on one worker
thread. Cancellation waits for that work to settle before propagating. It does
not interrupt the backend, undo effects, or provide a timeout guarantee. Give
backend operations bounded timeouts and keep the host alive until completion.
Async-only backend adapters are not supported by the synchronous host contract.

These tools cover the operations reached through this single registration.
SDK built-ins, dynamic tools added by other code, shell/browser access, unrestricted
code execution, and subagents are not automatically covered. Deep Agents'
filesystem/shell tools and smolagents' CodeAgent particularly require separate
restrictions. Multi-agent authority must use an explicitly bound
`MultiAgentHost` agent, not model-selected identities.

## Reproducing and extending validation

Build the native engine and create a fresh Python 3.12 environment, then run:

```sh
python scripts/test_integration.py strands --install
```

The isolated CI matrix uses the same command and the native engine from the same
commit. Missing required SDKs fail the job instead of silently skipping tests.
Tests drive actual SDK tool entry points with deterministic requests and inspect
backend effects. They cover denials, successful approved calls, changed and reused
approvals, and unknown outcomes. Shared host tests cover journal and snapshot
contracts; the async boundary additionally tests repeated cancellation.

Upgrade one SDK pin at a time, review its public invocation/schema changes, and
run its conformance job plus the repository gate. Expand mode/version claims only
with corresponding tests. No live model calls or provider credentials are needed
for these checks.
