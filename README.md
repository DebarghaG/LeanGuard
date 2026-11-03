# LeanGuard

LeanGuard sits between an AI agent and its tools and refuses calls that break your
policy. The policies are ordinary Lean 4 definitions, so you can prove things about
them, and the engine that evaluates them is itself proved to agree with a formal
temporal-logic semantics.

When the agent proposes a tool call, a small Python host intercepts it, reads the
relevant facts from your backend, and asks the compiled Lean engine for a decision.
The host writes that decision to a journal on disk, and only then runs the tool.
A denied call never reaches the backend.

## Try it

You need Linux, Python 3.12 or later with `venv`, Git and curl. The setup script
installs elan if it is missing, fetches the pinned Lean toolchain and the
LeanLTL and mathlib dependencies, builds the native engine, installs the Python
package into `.venv`, and runs a short demo.

```sh
git clone https://github.com/DebarghaG/LeanGuard.git
cd LeanGuard
git checkout v0.2.0-rc2
bash scripts/setup.sh
```

The demo policy says a document must be read before it is written, and that every
write needs the user's approval. Its output, trimmed:

```text
Unapproved write: {'allow': False, 'reasons': ['example.confirm', 'example.read_first'], ...}
Read: {'allow': True, 'outcome': 'success', 'result': {'value': 'initial'}, ...}
Approved fixture write: {'allow': True, 'outcome': 'success', 'result': {'value': 'updated'}, ...}
Backend calls: ['read', 'write']
```

The first write fails both rules. The read goes through, the host prepares an
approval request for the write, a hard-coded fixture plays the user and accepts
it, and the write succeeds. The backend only ever saw two calls. In a real
integration you replace that fixture with your own trusted approval screen.

To learn LeanGuard step by step, start with the [tutorials](docs/tutorials/README.md).

This is `0.2.0rc2`, a release candidate for dogfooding. Everything in the
repository, including the policy-authoring skill, is MIT-licensed. The
[release guide](scripts/README.md#release-candidates) explains how to build
platform wheels, which bundle the native engine and need only Linux and Python
3.12 at runtime.

## Writing a policy

A policy pack is a list of named rules:

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

Everything is denied unless a `permit` matches. A call is allowed when some permit
matches, every applicable `require` holds, and no `forbid` fires. `Formula`,
`Check`, `Rule`, `Schema` and `PolicyPack` are plain Lean types, so reusable
pieces of policy are just Lean functions.

To ship your own policy, create a separate Lake project and call `serve policy`
from `main`, or `serveVerified` if you have proved a safety property about the
pack. You don't need to edit anything in LeanGuard itself. The
[custom policy example](examples/custom_policy/Guard.lean) has a property
theorem, an audit target, the executable and a Python driver. The
[DSL guide](docs/native-dsl.md#add-a-pack) walks through the steps, and there is
an optional [policy-authoring skill](skills/leanguard-policy/SKILL.md) for coding
agents.

For a larger worked example, the [Dogwood guide encodings](examples/dogwood/README.md)
port all 86 examples from the Dogwood guide and compare them against the Dogwood
interpreter.

## Connecting your backend

The Python package exports `Engine`, `GuardHost`, `Adapter`, `Snapshot`,
`Proposal`, the `Decision` and `CallResult` result types, and the read-only
`audit` and `replay` functions. It has no third-party dependencies; MCP and the
τ² benchmark adapter are optional extras.

Your adapter implements two methods. `execute(action, arguments)` runs the real
tool. `snapshot(action, arguments, customer)` returns the facts the policy should
see: normalized arguments, their units, authoritative backend state, and a
revision string that changes whenever any of that state changes. The adapter also
exposes a `lock`, and every writer to the backend must take it, including writers
that don't go through LeanGuard. Without that, the facts Lean checked could be
stale by the time the tool runs. [`demo.py`](python/leanguard/demo.py) is a
complete small adapter, and [`host.py`](python/leanguard/host.py) defines the
contract.

Calls that need user approval go through a proposal:

```python
proposal = host.prepare(action, arguments)
accepted = trusted_user_ui(proposal.details)  # show the exact details, return True or False
host.confirm(proposal.id, accepted)
result = host.execute(action, arguments, proposal_id=proposal.id)
```

The approval is bound to those exact arguments and to the backend revision at the
time, and it can be used once. `trusted_user_ui` has to be something the agent
can't impersonate.

`host` is a `GuardHost` built from your adapter, a journal path, the principal
(the user or account the agent acts for) and a conversation ID. Use it as a
context manager so the engine process, database and journal lock are released.
`execute` checks the call with Lean before running it. The returned `CallResult`
always has `allow`, `request_id`, `reasons`, `errors` and `evidence`, and admitted
calls also report an `outcome`. Errors in the host or transport are raised as
exceptions, and nothing has been dispatched when that happens.

If a tool raises, LeanGuard records the outcome as unknown, since the call might
have changed state before failing. Raise `ReadOnlyToolError` instead when you know
a read failed without side effects. Adapters can also implement
`IdentityAdapter.resolve_identity(events)` to decide who the customer is from
trusted evidence in the session's history; by default identity comes only from
explicit identity observations.

Platform wheels find their bundled engine automatically, and source installs use
the checkout's Lake build. To use a custom policy executable, pass
`binary=Path(...)` or set `LEANGUARD_BINARY`. Read the
[guarantee boundary](docs/guarantees.md) before wiring up a real backend; it
lists what your adapter is trusted to get right.

## MCP

```sh
.venv/bin/pip install -e '.[mcp]'
.venv/bin/leanguard mcp --domain example --journal ./private/session.sqlite \
  --principal alice --session conversation-1
```

The server exposes three tools to the agent: `policy_manifest`,
`available_tools` and `guarded_call`. Don't give the agent the underlying tools
as well, or it can go around the guard. Approval, identity and policy loading
are not available as agent tools.

The command-line server has no approval screen, so writes that need approval are
denied. To allow them, run the Python confirmation flow above and pass its
proposal ID to `guarded_call`, or build the server yourself with
`build_server(host, approval=trusted_callback)`, where the callback shows the
`Proposal` to a real user and returns their answer.

With the optional benchmark dependency you can also use `--domain retail`,
`airline` or `telecom`. Those adapters use in-memory databases with fixed clocks,
so restarting the server starts a fresh backend. That's fine for development, but
a real integration has to restore its backend itself before reusing a journal;
LeanGuard never re-executes journaled calls.

## Multiple agents and A2A

`MultiAgentHost` lets several agents share one journal. Each agent has a bound
identity and acts under a grant, and grants can be delegated only with narrower
actions, resources, limits and expiry. Every call is charged against the budget
of each ancestor grant, so two workers can't each spend their parent's full
allowance. Local tools keep their usual policy and approval checks.

The optional A2A 1.0 client (HTTP and JSON) can send messages, poll, cancel, and
stream task updates, and it tracks which agent owns each remote task and context.

The [multi-agent guide](docs/multi-agent.md) covers the trust boundary, the API,
which parts of A2A are supported, and the LeanLTL contracts, including a proof
that terminal task states are final and a counterexample showing why eventual
completion can't be guaranteed. To see it run:

```sh
.venv/bin/python examples/multiagent/run.py
```

## What is proved

Lean proves that the temporal evaluator and the full admission decision agree with
their LeanLTL meanings, including time windows, scope projection, empty histories
and the rule that any evaluation error means denial. The
[LeanLTL guide](docs/leanltl.md) lists the theorems and shows how to use them.

The proofs stop at the Lean engine. They say nothing about the Python host, the
benchmark tools, or whether a domain rule faithfully captures the English policy
it came from. Getting real facts out of the backend, converting units correctly,
showing the user what they are approving, intercepting every tool call, keeping a
trustworthy clock, and the correctness of the Lean compiler are all assumptions
about your deployment. The [guarantee boundary](docs/guarantees.md) spells them
out.

The retail, airline and telecom packs cover 43 tools from the τ² benchmark, with
compiled input schemas. [Coverage and interpretations](docs/coverage.md) records
which policy clauses are enforced, how ambiguous ones were read, and which are
left out. The monitor keeps the full history and evaluates it with a reference
evaluator, so throughput at production scale is untested.

## Verification

```sh
.venv/bin/pip install -e '.[test,mcp]'
.venv/bin/python scripts/verify.py
```

This builds the Lean code, checks that the proofs use only Lean's standard axioms,
runs the Python linter and tests, and checks the Dogwood article examples. Tests
for optional integrations are skipped when their dependencies are missing, and
tests that call a live model (marked `live`) never run by default. The
[tooling guide](scripts/README.md) explains how to run the pinned τ² tests.

## Experiments

These are opt-in and outside the supported library.

### Repair suggestions

When a call is denied, the
[Lean repair experiment](examples/repair/README.md) searches a list of candidate
edits for one that the policy allows, and prints a proof you can replay. It uses
a policy-specific configuration of Lean's `grind` solver: you register policy
lemmas with `guard_rule` and use them through `guard_solve` or `guard_repair?`.
The [grind study](docs/grind.md) explains which parts of `grind` it builds on.

### Replaying saved traces

You can check a recorded history against a policy without running any tools:

```python
from leanguard import Engine, replay

with Engine("example") as engine:
    for result in replay(engine, events):  # host.events(), oldest first
        print(result["request_id"], result["assessment"])
```

`leanguard replay DOMAIN events.jsonl --binary /path/to/custom-engine` does the
same from the shell. The [trace format](docs/native-dsl.md#recorded-trace-api)
describes what each event needs and how to mark missing evidence.

### Model evaluations

The [experiment guide](scripts/experiments/README.md)
covers paired runs with a local Qwen3.5-4B model, scoring saved episodes, and
auditing published rollouts from other projects. Replaying someone else's
trajectory tells you which calls LeanGuard would have blocked; it can't tell you
whether the task would still have succeeded with those calls blocked.
