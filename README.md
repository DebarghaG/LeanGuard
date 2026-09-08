# LeanGuard

Agent tool guardrails written and evaluated in Lean 4. Policies are ordinary Lean
declarations, not a separate language translated into Lean. A small Python host
intercepts tool calls, obtains trusted observations, records admission durably, and
dispatches only after the native engine permits the call.

The design is inspired by Dogwood's event/policy separation and temporal guards.
See the [article conformance notes](scripts/README.md#article-conformance) for the
implemented examples and their assumptions.

## Run

This is `0.2.0rc2`, a source release candidate for dogfooding. LeanGuard's code,
examples, documentation, and policy-authoring skill are MIT-licensed.

Requirements: Linux, Python 3.12+ with `venv`, Git, and curl. The setup command
installs elan if needed, fetches the pinned Lean toolchain and LeanLTL/mathlib
dependencies, builds the native runtime, and installs Python into `.venv`.

```sh
git clone https://github.com/DebarghaG/LeanGuard.git
cd LeanGuard
git checkout v0.2.0-rc2
bash scripts/setup.sh
```

The demo denies an unapproved write, reads the document, records a fixture
confirmation, and executes the approved write. Replace that fixture with a trusted
user interface in an integration.

The [release guide](scripts/README.md#release-candidates) also explains how to
build platform wheels locally. Those wheels include the native executable and
require only Linux and Python 3.12+ at runtime.

## Python integration

The core exports `Engine`, `GuardHost`, `Adapter`, `Snapshot`, `Proposal`, typed
`Decision`/`CallResult` results, and read-only `audit`/`replay` APIs. It has no
third-party Python dependencies. MCP and the τ² adapter are optional integrations.

Implement `Adapter.snapshot(action, arguments, customer)` and
`Adapter.execute(action, arguments)` for your backend, with a shared `lock` that
serializes **every** backend writer. A snapshot supplies authoritative facts,
normalized arguments, declared units and a revision covering all relevant state.
Changing those facts or state must change the revision. See the small
[example adapter](python/leanguard/demo.py) and [adapter contract](python/leanguard/host.py).

For actions that need consent, the integration sequence is:

```python
proposal = host.prepare(action, arguments)
accepted = trusted_user_ui(proposal.details)  # Display the exact details; return a Boolean.
host.confirm(proposal.id, accepted)
result = host.execute(action, arguments, proposal_id=proposal.id)
```

`host` is a `GuardHost` created with your adapter, journal path, trusted principal
and conversation ID. Use it as a context manager so the native process, database
and journal lock are closed. `execute` performs the native admission check before
dispatch; callers should check `allow` and `outcome`. Use `ReadOnlyToolError` only
for a certified read failure with no state change; other tool exceptions have an
unknown outcome. MCP adapters additionally provide `tool_schemas()` and
`mutating(action)`.

Platform wheels discover their bundled executable automatically. Source/editable
installs use the checkout's Lake build. Custom policy executables can be selected
with `binary=Path(...)` or `LEANGUARD_BINARY`. `CallResult` always includes `allow`,
`request_id`, `reasons`, `errors`, and `evidence`; admitted calls additionally report
their execution `outcome`. Host/transport errors raise exceptions; callers must not
dispatch on those errors. Adapters may implement `IdentityAdapter.resolve_identity(events)`
to interpret trusted identity evidence; the default uses explicit identity observations.
See [the guarantee boundary](docs/guarantees.md) before adapting a backend.

## Native Lean DSL

```lean
import LeanGuard.Policy
open LeanGuard

def policy : PolicyPack := { name := "documents", rules := [
  permit "tools" ["read", "write"],
  require "read_first" ["write"] (observed ["read"]) "read this resource first",
  require "approval" ["write"] confirmed "matching, unrevoked, unused approval",
  require "budget" ["write"] (quota 10 10000 3600) "dispatch count and amount cap"
] }
```

`Formula`, `Check`, `Rule`, `Schema`, and `PolicyPack` are Lean types. Reusable policy
constructs are Lean functions. A separate Lake project can use `serve policy`, or
`serveVerified verifiedPolicy` to associate admission with a proved safety contract.
No registry edit is required. The [downstream example](examples/custom_policy/Guard.lean)
includes a property theorem, audit target, executable, and Python integration.
The [Dogwood guide encodings](examples/dogwood/README.md) exercise 86 external
examples with a separate native registry and reproducible replay comparisons.
See the [DSL guide](docs/native-dsl.md#add-a-pack) and optional
[policy-authoring skill](skills/leanguard-policy/SKILL.md).

## MCP

```sh
.venv/bin/pip install -e '.[mcp]'
.venv/bin/leanguard mcp --domain example --journal ./private/session.sqlite \
  --principal alice --session conversation-1
```

The server exposes `policy_manifest`, `available_tools`, and `guarded_call`.
Underlying tools must not also be exposed directly to the agent. There is no
agent-facing approval, identity, observation-injection, or policy-loading tool.
The CLI has no approval UI, so approval-required writes are denied. Use the Python
confirmation flow above and pass its proposal ID to `guarded_call`, or supply
`build_server(host, approval=trusted_callback)`. That callback receives a `Proposal`
and must return a Boolean from a trusted user decision after displaying its details.

Use `--domain retail`, `airline`, or `telecom` with the optional benchmark dependency.
Benchmark adapters have fixed domain clocks and in-memory databases. The CLI is a
development harness: restarting it creates a new backend database, **not** a durable
backend recovery. Integrations must restore the actual backend separately before
reusing a journal. The guard's journal never re-executes recorded tool calls.

## Guarantees and limits

Lean proves that temporal evaluation and the complete admission decision agree with
their LeanLTL meanings, including metric windows, scope projection, empty histories,
and the error gate. See [the LeanLTL integration and proof API](docs/leanltl.md).

This is **not** a proof of the Python host, the benchmark tools, all English policy
clauses, or a refinement from real-world actions to those traces. Authentic facts,
correct unit conversion, faithful confirmation presentation, complete interception,
trusted clocks, backend synchronization, and compiler/runtime correctness remain
deployment assumptions. See [the guarantee boundary](docs/guarantees.md).

The retail, airline, and telecom packs cover 43 assistant tool names with compiled
input schemas and action scopes. [Coverage and interpretations](docs/coverage.md)
records the implemented subset and unformalized prose rules. The monitor retains
complete histories and uses a reference evaluator; production-scale throughput is
not established.

## Verification

```sh
.venv/bin/pip install -e '.[test,mcp]'
.venv/bin/python scripts/verify.py
```

The gate builds Lean, audits proof axioms, checks Python lint and tests, and runs
native article conformance. Tests for optional integrations skip when dependencies
are absent. Ordinary pytest runs and the gate exclude tests marked `live`.
See [the tooling guide](scripts/README.md) to enable the pinned τ² integration tests.

## Experiments

For normalized saved events, the installed library supports read-only replay:

```python
from leanguard import Engine, replay

with Engine("example") as engine:
    for result in replay(engine, events):  # host.events(), oldest first
        print(result["request_id"], result["assessment"])
```

`leanguard replay DOMAIN events.jsonl --binary /path/to/custom-engine` exposes the
same API. Preserve recorded dispatches/outcomes and mark incomplete evidence; see
the [trace contract](docs/native-dsl.md#recorded-trace-api).

The [experiment guide](scripts/experiments/README.md) covers paired Qwen3.5-4B runs,
saved-episode scoring, external rollout replay, and opt-in live protocol tests.
These runners and dataset loaders live in `scripts/experiments/`, outside the
installed Python package. Replay audits the recorded trajectory; it does not
measure task success after blocking calls.
