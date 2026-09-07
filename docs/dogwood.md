# Correspondence with Dogwood

Reference: Dogwood checkout `c6237c88099b3f492ecc5fcee42df06a19224b97`, especially
its [event schema](https://github.com/dogwood-policy/dogwood/blob/c6237c88099b3f492ecc5fcee42df06a19224b97/dogwood-docs/guide/03-event-schema.md)
and [temporal language](https://github.com/dogwood-policy/dogwood/blob/c6237c88099b3f492ecc5fcee42df06a19224b97/dogwood-docs/guide/04-temporal-expressions.md).
This is conceptual alignment, not a claim of complete language compatibility or a
machine-checked equivalence with Dogwood.

| Dogwood concept | LeanGuard representation | Difference or gap |
|---|---|---|
| Principal/action/resource/context | `Event` and `Context` | IDs are strings; domain data is decoded from JSON, not dependent records |
| Typed action schema | Compiled `Schema` and `withSchemas` | Runtime native validation, not Dogwood/Cedar's complete static type system |
| Event schema and decision points | Request, dispatch, outcomes, trusted observations; historical input/output payloads | Fixed v1 event protocol; only admission decides |
| Permit/forbid, default deny | `Effect`, `Rule`, `authorize` | Adds mandatory `require`, so an unrelated permit cannot bypass an invariant |
| Temporal condition plus stateless predicates | `Formula Check`, pure `Check.run` | One Lean representation and evaluator; no Cedar lowering |
| `formerly`, `previous`, `since` | `once`, `previous`, `since` | Same basic past-time operators and inclusive bounded-window convention |
| Universal symmetric pins | Explicit `within` history projection | Matches key-local intent, but not automatically imposed on every custom rule |
| Correlated approval/revocation | `confirmed`, `confirmedWithin`, and reusable response predicates | One-use bound approval and reusable article-style approval are separate policies |
| Count/distinct/sum aggregation | Typed `WindowQuery` over requests, dispatches, or successes | Native functions, exact natural numbers; no general first-order relational query DSL yet |
| Bind aggregate result | Ordinary Lean `let` in a `Check` | No additional binder syntax or external evaluator |
| Information providers | Pure native predicates plus trusted fact adapters | Provider-style effects are outside the proved kernel; OPA is deferred |
| Replay/debugging | Versioned durable journal, manifest, native audit operation | Direct full-history evaluator; no optimized streaming backend yet |
| Bounded retention / `max_window` | Explicit bounded or unbounded operators | No mandatory global cap; complete history is retained in v1 |

The important shared practices are separating a proposed call from its outcome,
making temporal evidence resource/principal-correlated, projecting history before
`previous`/`since`, schema-checking inputs, making deny authoritative, and keeping
policy evaluation separate from actual execution.

Lean adds a direct route to proofs about the executable representation. It does not
automatically provide Dogwood's schema inference, universally pinned isolation,
first-order join expressiveness, monitor efficiency, or end-to-end host verification.
Those should not be advertised as already implemented merely because the DSL is Lean.

The introduction article's supplied traces now have an executable native
[conformance suite](dogwood-conformance.md): all 28 original verdicts match, with
additional boundary, adversarial, live protocol, host, and MCP checks. This establishes
the tested examples, not universal equivalence with the Dogwood interpreter.
