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

For the pinned benchmark integration and its tests:

```sh
git clone https://github.com/sierra-research/tau2-bench.git .tau2
git -C .tau2 checkout 672227c6b6676edc20d57ea53b7000262aae77b9
.venv/bin/pip install -e .tau2
.venv/bin/pytest -q tests/test_tau.py
```

The editable checkout retains the benchmark's data directory and lets the rollout
runner verify its revision. It is ignored by this repository, as are local models,
virtual environments, journals, and experiment outputs.

The benchmark pin is `672227c6b6676edc20d57ea53b7000262aae77b9` of
[tau2-bench](https://github.com/sierra-research/tau2-bench/tree/672227c6b6676edc20d57ea53b7000262aae77b9).
These are instrumented current text-domain tests, not an unmodified original τ²
leaderboard run. No LLM credentials or paid model calls are needed for these tests.

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
.venv/bin/python -m leanguard.conformance
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
