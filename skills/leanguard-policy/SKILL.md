---
name: leanguard-policy
description: Author, prove, and integrate custom LeanGuard runtime tool policies in Lean. Use when creating or changing a policy package, its safety theorem, backend adapter, or recorded-trace audit.
license: MIT
---

You're building a downstream Lean package that defines a tool policy, proves a safety
property about it, and ships it as an executable that LeanGuard's Python host can run.
Pin a [LeanGuard](https://github.com/DebarghaG/LeanGuard) revision and read the docs
from that same checkout: `docs/native-dsl.md` for the policy language and
`docs/guarantees.md` for what is proved and what the integration must supply. Start
from a copy of `examples/custom_policy/`. Anyone who only runs a prebuilt policy needs
neither this skill nor Lean.

## Authoring

- Before writing rules, pin down the tool schemas, the authoritative facts and their
  units, how principal, session and resource scope the policy, and which decisions
  need structured user consent. A missing fact must surface as an explicit error. User
  approval comes only from the host's confirmation flow; tool outputs and the acting
  agent's claims never count as approval.
- Write a `PolicyPack` from named `permit`, `require` and `forbid` rules, preferably in
  record syntax, and wrap it with `withSchemas`. Tools without a schema stay denied.
  Reach for `confirmed`, `confirmedWithin`, `observed`, `quota` and `singleFlight`
  whenever their documented meaning is what the policy asks for.
- State the safety property you actually want as a `Context → Prop`, and write it
  independently of the implementation, so that a mistake in the rules shows up as a
  failed proof. Prove that `decidePolicy` admission implies it, and package the result
  as a `VerifiedPolicy`: `property` names the statement, `Safe` states it, and `sound`
  proves the implication. A property that is trivially true, or a pack that denies
  everything, also type-checks, so review the property itself.
- A custom predicate needs its own argument that it matches the English rule it
  encodes. The generic temporal correctness theorem covers the evaluator, not your
  predicates.

## Build and verification

Use `LeanGuard.serveVerified verified` as the executable's entry point, and keep the
audit in a default Lake target. The audit imports the executable and runs:

```lean
run_cmd do
  LeanGuard.Audit.check
    #[``MyPolicy.verified, ``MyPolicy.safe, ``main]
    #[`MyPolicy, `LeanGuard]
```

Substitute your own declarations. The roots must cover the deployed pack, its property
theorem and the executable. Auditing whole namespaces also catches unfinished
declarations nobody uses, and the transitive check catches dependencies outside those
namespaces. Plain `lake build` and `lake env lean` are all you need. Never use `sorry`, a custom axiom or
`native_decide` to get the release audit to pass.

Proofs and trace tests catch different mistakes, so do both. Drive allowed and denied
calls through a real `GuardHost` and adapter, and check the backend's actual effects.
Cover whichever of these apply: wrong resources or principals, altered arguments,
consent that is stale, revoked or reused, time boundaries, missing facts, and outcomes
that come back unknown.

## Runtime and replay

Implement `Adapter.snapshot` and `Adapter.execute`. A snapshot carries the normalized
arguments with exact units, the authoritative facts, and a revision that changes
whenever any relevant state changes. The adapter's lock, or an equivalent backend
transaction, must cover every writer. The acting agent only gets `GuardHost.execute`
or guarded MCP calls. Native control channels, backend credentials, identity
assignment and `confirm` all stay in trusted host code.

The consent flow is `prepare → trusted user presentation → confirm → execute`, which
binds the approval to the exact proposal. The acting agent must never be able to
rewrite the deployed policy or approve its own calls. Return a generic denial to the
agent and keep the diagnostics for the host.

For offline analysis, use `audit` and `replay` on normalized `TraceEvent` records in
chronological order. Keep the recorded dispatches and outcomes, and never fill in
consent that isn't in the trace. Mark incomplete histories and missing evidence, and
read `assessment` rather than the raw decision, which is conditional on the evidence
supplied.

Build and audit in development and CI, then deploy the compiled executable via
`binary=...`. Changing the executable requires migrating its journals. At run
time the host evaluates the compiled policy; no LLM is called and no proof search runs.
