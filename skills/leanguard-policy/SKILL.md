---
name: leanguard-policy
description: Author, prove, and integrate custom LeanGuard runtime tool policies in Lean. Use when creating or changing a policy package, its safety theorem, backend adapter, or recorded-trace audit.
license: MIT
---

Build a downstream policy package against a pinned LeanGuard revision. Read the
matching checkout's `docs/native-dsl.md` and `docs/guarantees.md`, and start from
`examples/custom_policy/`. The source repository is
[LeanGuard](https://github.com/DebarghaG/LeanGuard); use documentation from the same
revision as the dependency. Consumers of a prebuilt policy do not need this skill
or a Lean installation at runtime.

## Authoring

- Establish tool schemas, authoritative facts and units, principal/session/resource
  scope, and which decisions need structured consent. Missing facts are explicit
  errors. Tool outputs and the acting agent's claims do not establish user approval.
- Write a `PolicyPack` using named `permit`, `require`, and `forbid` rules, then
  apply `withSchemas`. Prefer record syntax for packs. Reuse `confirmed`,
  `confirmedWithin`, `observed`, `quota`, and `singleFlight` where their documented
  meanings match the requested policy. Unknown tools remain default-denied.
- State the intended safety property as `Context → Prop` independently enough to
  reveal a mistaken implementation. Prove that actual `decidePolicy` admission
  implies it. Package the result in `VerifiedPolicy`; `property` names the statement,
  `Safe` states it, and `sound` proves the implication. A proof of `True`, or an
  all-denying policy, does not establish useful coverage of the requested behavior.
- Custom predicates need their own correspondence arguments where appropriate.
  The generic temporal correctness theorem does not prove English-policy fidelity,
  authentic observations, natural-language consent understanding, or eventual success.

## Build and verification

Use `LeanGuard.serveVerified verified` for the executable entry point. Keep the
audit in a default Lake target. Import the downstream executable and run:

```lean
run_cmd do
  LeanGuard.Audit.check
    #[``MyPolicy.verified, ``MyPolicy.safe, ``main]
    #[`MyPolicy, `LeanGuard]
```

Replace the names with actual declarations. The roots must include the deployed
pack, its property theorem, and the executable. The namespace audit includes unused
unfinished declarations, and transitive auditing catches dependencies outside those
namespaces. Use ordinary `lake build` and `lake env lean`; the workflow has no
dependency on LeanBeam or editor-specific Lean skills. Do not use `sorry`, custom
axioms, or `native_decide` to satisfy the release audit.

Exercise allowed and denied calls through a real `GuardHost` and adapter. Include
wrong resources/principals, altered arguments, stale/revoked/reused consent, time
boundaries, missing facts, and uncertain outcomes as relevant to the policy. Check
actual backend effects. Proof checks and trace examples serve different purposes.

## Runtime and replay

Implement `Adapter.snapshot` and `execute`. Snapshot normalized arguments, exact
units, authoritative facts, and a revision covering every relevant state change.
The adapter lock or equivalent backend transaction must cover every writer. Keep
the acting agent on `GuardHost.execute` or guarded MCP calls; native control channels,
backend credentials, identity assignment, and `confirm` stay with trusted host code.

`prepare → trusted user presentation → confirm → execute` binds approval to the
exact proposal. Do not let the acting agent rewrite deployed policy or issue its
own consent. Return generic denial to the agent and retain diagnostics for the host.

For offline work use `audit`/`replay` with normalized chronological `TraceEvent`
records. Preserve recorded dispatches and outcomes; never synthesize missing consent.
Declare incomplete history and missing evidence, and inspect `assessment` separately
from the raw conditional decision. Replay cannot measure success after enforcement.

Build and audit during development/CI, then deploy the compiled executable through
`binary=...`. A changed executable needs deliberate journal migration. Runtime calls
evaluate the compiled policy; they do not invoke an LLM or search for new proofs.
