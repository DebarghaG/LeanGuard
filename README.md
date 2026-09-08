# LeanGuard

Agent tool guardrails written and evaluated in Lean 4. Policies are ordinary Lean
declarations, not a separate language translated into Lean. A small Python host
intercepts tool calls, obtains trusted observations, records admission durably, and
dispatches only after the native engine permits the call.

This is an independent implementation inspired by Dogwood's event/policy separation,
past-time temporal operators, correlated histories, and deny-overrides decisions.
Neither Dogwood nor OPA is a dependency. OPA integration is deferred.

## Run

Requirements: Linux, Python 3.12, Git, and elan. The checked-in toolchain pins Lean
4.33.1; Lake pins the upgraded LeanLTL fork and mathlib. No lean-beam is needed.

```sh
git clone https://github.com/DebarghaG/LeanGuard.git
cd LeanGuard
lake update
lake exe cache get
lake build
python3.12 -m venv .venv
.venv/bin/pip install -e '.[test,mcp]'
.venv/bin/leanguard demo
.venv/bin/pytest -q
lake env lean Audit.lean
```

The demo denies an unapproved write, reads the document, records an explicit trusted
fixture confirmation, and executes the approved write. It does not ask an LLM to
decide whether consent occurred.

The optional benchmark adapter and evaluation setup are documented in
[the repository tooling guide](scripts/README.md). Dataset downloaders, model
launchers, scoring and replay runners live in `scripts/experiments/`; they are
excluded from the installed `leanguard` package.

## Python integration

The public library exports `Engine`, `EngineError`, `GuardHost`, `Adapter`,
`Snapshot`, `Proposal`, and `ReadOnlyToolError`. The core has no third-party Python
dependencies. MCP and the τ² adapter are optional integrations.

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

The Python wheel does not bundle a compiled Lean executable. When using it outside
an editable source checkout, supply `binary=Path(...)` to `Engine`/`GuardHost`, or
set `LEANGUARD_BINARY` to the absolute path of the executable built by Lake. See
[the guarantee boundary](docs/guarantees.md) before adapting a real backend.

## Native Lean DSL

```lean
import LeanGuard.Policy
open LeanGuard

def policy : PolicyPack := ⟨"documents", [
  permit "tools" ["read", "write"],
  require "read_first" ["write"] (observed ["read"]) "read this resource first",
  require "approval" ["write"] confirmed "matching, unrevoked, unused approval",
  require "budget" ["write"] (quota 10 10000 3600) "dispatch count and amount cap"
]⟩
```

`Formula`, `Check`, `Rule`, `Schema`, and `PolicyPack` are Lean types. Reusable policy
constructs are Lean functions. The runnable packs are compiled into `Runtime.packFor`;
an agent cannot upload or select replacement policy code at runtime. See
[the compiled example](LeanGuard/Examples.lean) and [the DSL guide](docs/native-dsl.md).

## Dogwood article examples

```sh
.venv/bin/python -m scripts.conformance
.venv/bin/pytest -q tests/test_dogwood.py
```

All seven supplied trace fragments (28 request verdicts) are reproduced by native Lean
policies. The runner also checks the running-sum boundary, confidentiality example,
and adversarial cases: 21 traces and 73 verdicts total. It includes the deliberately
unsafe response-only sum as a negative control, confirming that it permits the burst
that request-based accounting rejects. The unsafe pack is unavailable to live admission.

Historical inputs/outputs, bounded approvals, explicit request/dispatch/success query
bases, distinct counts, and aggregate comparisons are implemented in
[Query.lean](LeanGuard/Query.lean) and [DogwoodExamples.lean](LeanGuard/DogwoodExamples.lean).
[Conformance details](docs/dogwood-conformance.md) distinguish literal article semantics
from the existing single-use approval and dispatch-budget guards. No Dogwood runtime,
Cedar parser, separate policy DSL, or OPA service is involved.

## MCP

```sh
.venv/bin/leanguard mcp --domain example --journal ./private/session.sqlite \
  --principal alice --session conversation-1
```

The server exposes `policy_manifest`, `available_tools`, and `guarded_call`.
Underlying tools must not also be exposed directly to the agent. There is no
agent-facing approval, identity, observation-injection, or policy-loading tool.
The default CLI does not supply an approval UI, so approval-required writes are
denied. Integrators can call `host.prepare`, display `proposal.details` on a trusted
user surface, call `host.confirm`, then pass the proposal ID to `guarded_call`.
`build_server(host, approval=trusted_callback)` supports that same flow. A callback
must obtain a real user decision; an unconditional `True` is only a test fixture.
MCP elicitation responses are not assumed to constitute trusted user consent.

Use `--domain retail`, `airline`, or `telecom` with the optional benchmark dependency.
Benchmark adapters have fixed domain clocks and in-memory databases. The CLI is a
development harness: restarting it creates a new backend database, **not** a durable
backend recovery. Integrations must restore the actual backend separately before
reusing a journal. The guard's journal never re-executes recorded tool calls.

## Guarantees and limits

Lean proves that every temporal formula's executable evaluation agrees with its
compositional LeanLTL interpretation, including metric windows, scope projection,
and empty histories. The complete admission decision is equivalent to its LeanLTL
policy meaning, including permit existence, mandatory rules, forbids, and the error
gate. Confirmation, query membership, and monitor replay also have LeanLTL
correspondence theorems; quota reservation preserves the checked bounds.
`native_trace_leanLTL_safe` expresses admission safety globally over finite or infinite
traces of contexts. See [the LeanLTL integration and proof API](docs/leanltl.md).

This is **not** a proof of the Python host, the benchmark tools, all English policy
clauses, or a refinement from real-world actions to those traces. Authentic facts,
correct unit conversion, faithful confirmation presentation, complete interception,
trusted clocks, backend synchronization, and compiler/runtime correctness remain
deployment assumptions. See [the guarantee boundary](docs/guarantees.md).

All 43 assistant tool names across retail, airline, and telecom have compiled input
schemas and policy action scopes. That does not mean every prose rule is formalized
or every tool has a full end-to-end test. [Coverage and interpretations](docs/coverage.md)
records the implemented safety subset and remaining gaps.

## Local model evaluation

The optional [local Qwen3.5-4B experiment](docs/local-benchmark.md) runs the pinned
retail, airline, and telecom tasks with vLLM in parallel, using baseline, generic
denial, and actionable-feedback arms. Longer rollouts retain invalid generations,
denial checkpoints, admission-recovery metrics, task scores, and reproducibility metadata.
Local customer simulation and LLM judging are explicitly separated from the
guarantees of the Lean policy engine.

The [published trajectory replay](docs/external-rollouts.md) injects native policy
checks into external Hugging Face rollouts without model calls or tool execution.
It accounts for training prefixes, reports missing evidence and unsupported code
tools separately, and exports every decision for native rechecking.

## Verification

```sh
.venv/bin/python scripts/verify.py
```

This builds Lean, audits proof axioms, runs Python lint and tests, and prints policy
coverage counts and the article conformance report. Tests include real benchmark mutations,
invalid calls that the
underlying tool would accept, schema errors, approval reuse/revocation, concurrency,
engine crashes, journal failures, replay corruption, and both MCP transports.
The benchmark tests skip when the optional dependency is absent.

The default `lake build` also checks the LeanLTL theorem regressions and rejects
nonstandard transitive axiom dependencies across the public LeanGuard declarations.

The v1 monitor retains complete histories and uses a direct reference evaluator.
It is suitable for validating semantics and instrumented experiments, not a claim of
production-scale throughput. Incremental monitoring, typed domain records, richer
cross-event joins, external policy adapters, and full benchmark evaluation are next
steps. See [the Dogwood correspondence](docs/dogwood.md).
