# Dogwood guide dogfooding

This separate Lake project encodes all **86** examples in the
[Dogwood guide index](https://dogwood-policy.github.io/dogwood/examples/index.html)
using LeanGuard's existing public APIs. It does not add policies to the production
registry or implement a Dogwood language frontend.

Source: [dogwood-policy/dogwood at c6237c8](https://github.com/dogwood-policy/dogwood/tree/c6237c88099b3f492ecc5fcee42df06a19224b97/dogwood-docs/examples).
Upstream bundles remain in their Apache-2.0 checkout. Our native implementation,
adapter and tests are covered by LeanGuard's MIT license.

## What is represented

| Approach | Examples | Boundary |
| --- | ---: | --- |
| Native predicates and temporal operators | 65 | Normalized, typed event records |
| Additional data adapters | 10 | Entity type/membership, optional request context, clock, or custom event kinds |
| Information-provider adapters | 11 | Trusted typed provider results; no proof of Rhai, regex or a classifier |

**84 examples can be compared against the actual Dogwood interpreter.** The other
two, `sell_after_2024_datetime` and `sell_datetime_window`, have native encodings
and independent clock-boundary checks, but are not counted as differential
successes. At the pinned revision, Dogwood's event `Value` type and log parser
cannot carry a datetime. Supplying an ISO timestamp produces
`expected datetime, got string`. Both source policies validate, and neither has
a published trace. We retain these errors in the report and check the intended
clock predicates separately; we do not change the upstream engine.

## Run

From the LeanGuard repository root, with the development Python environment
installed as described in the main README:

```sh
git clone https://github.com/dogwood-policy/dogwood /tmp/dogwood-guide-source
git -C /tmp/dogwood-guide-source checkout c6237c88099b3f492ecc5fcee42df06a19224b97
cargo build --manifest-path /tmp/dogwood-guide-source/Cargo.toml -p amzn-dogwood-cli
cd examples/dogwood
lake build
cd ../..
.venv/bin/python -m unittest discover -s examples/dogwood -p 'test_*.py' -v
.venv/bin/python examples/dogwood/run.py \
  --source /tmp/dogwood-guide-source \
  --dogwood /tmp/dogwood-guide-source/target/debug/dogwood
```

Rust is needed only to build the comparison engine. LeanGuard's standalone
example binary and the Python adapter do not invoke Rust. The runner requires a
clean pinned source checkout, allowing generated Cargo.lock and target/ build
outputs. Preserve that lockfile with your reference build if reproducing its
dependency resolution.

`run.py` validates every source bundle, checks every published trace against
both the original CLI and `expected.out`, and runs the generated scenarios from
`cases.py`. No expected verdict is used to construct a native policy. It exits
nonzero on an unexpected disagreement or evaluation error. For the two clock
examples it explicitly checks that the documented source limitation still holds.
An interrupted report lacks the final `summary` field.

The ignored `results.json` records source-file and binary SHA-256 hashes, a hash
of each generated trace, decision counts, and every disagreement. Temporary traces,
upstream dependencies, binaries and raw reports are excluded from source distribution.

## Semantics that matter

- **One line is one timepoint.** Equal timestamps remain distinct positions.
  `formerly` includes the current position; windows include their endpoints.
  Default principal pins project the history before `previous` and `since`.
  The two explicitly unpinned alert schemas and the raised-window schema retain
  global history. Resource correlation is added only where the source asks for it.
- **Logged data and current request context are separate.** A historical response
  becomes a `success` record for matching purposes, even if its output contains
  `result: false`. Only a policy explicitly checking that output requires true.
  Neither a response nor an approval-named request becomes a user confirmation.
  Denied requests and recorded outcomes remain in replay history.
- **Custom kinds have an explicit mapping.** Only the `login_attempt_custom_kind`
  schema maps `attempt` to request and `outcome` to response. The adapter rejects
  unsupported kinds and disagreements between logged actor/resource and scope.
- **Aggregation respects the binder.** Counts refer to positions, not unique
  timestamps or amounts. The `(amount,timepoint)` sums retain repeated values and
  use signed integers. The current-only amount sum deduplicates its value domain.
  These examples compare sums against small bounds; exact integer totals and
  Dogwood's final signed-64 saturation give the same threshold comparison.
- **Providers are outside the proof boundary.** The small adapters reproduce the
  shipped provider fixtures and pass individual results into Lean, where the
  policy combines them. Dogwood evaluates its original Rhai independently.
  For example, `Content::Risk` here is the source's fixed keyword lookup, not an
  actual content classifier. The regex adapter uses whole-string matching to
  preserve Rust's end-anchor behavior for a final newline.
- **The comparison domain is explicit.** It uses each example's finite action
  schema, typed Cedar Long inputs, integer-second event timestamps and coherent
  scope fields. Decimal context values use exact signed four-place coefficients;
  clocks use UTC milliseconds. This adapter is not a general Cedar parser or
  entity-store validator. Error recovery and malformed-record behavior across the
  two complete languages are not claimed equivalent.

Several source examples are weaker than their names or comments suggest:

- `read_login_not_logout` negates a Logout at the **current** position. A previous
  Logout does not invalidate an earlier Login. The generated trace tests this.
- `temporal_login_then_read` and its composed-macro counterpart require both
  events within the hour, without requiring Login to precede Read.
- `write_after_read` actually gates SellShares on an ApproveSale response for the
  stock. It does not check the approval's Boolean output or consume it.
- Seven examples always deny in the single-event-per-timepoint model:
  `alert_heartbeat_and_login_rate`, `alert_login_current_tp`,
  `alert_total_transfer_over_200`, `read_heartbeat_since_login_30s`,
  `read_since_login`, `forbid_large_except_amzn`, and
  `forbid_read_transfers_over_1000`. The first five require an incompatible current
  event or current-only aggregate. The last two contain no permit rule. For these
  forbid-only packs, the runner also compares whether the forbid fires, so a
  broken threshold or sum cannot hide behind default denial.

These behaviors are intentionally preserved. This is a representation exercise,
not an endorsement of these rules as suitable production guardrails.

## Proof scope

`lake build` checks `GuideAudit.lean`, including the runtime entry point and the
entire imported LeanGuard/guide declaration namespaces. The audit rejects
`sorryAx` and custom axioms; only Lean's standard `propext`, `Classical.choice`
and `Quot.sound` are allowed.

`DogwoodGuide.sound` connects every encoded decision, including the error gate,
to its LeanLTL meaning through `decision_leanLTL_correct`.
`DogwoodGuide.access_witness` additionally exposes a grant witness within the hour
and absence of matching revocations at every later position in the principal's
history. For the published access example, replay yields
**Grant: deny → Access: allow → Revoke: deny → Access: deny**.

These are kernel-checked theorems about the encoded policies and supplied facts.
Replay agreement is testing evidence for the manual ports, **not a proof of
equivalence to Dogwood's Rust implementation**, truthful logs, or external
provider results. No new production API or formal-policy relaxation was needed.

## Repair experiments

[Repairs.lean](Repairs.lean) uses `guard_repair?` with complete LeanLTL policy goals.
It shows a sale of 100 shares repaired to 99 when the task explicitly permits a
smaller positive sale. If the task requires exactly 100, the same example proves
that no permitted edit can pass. It also proves that the two forbid-only guide
policies cannot admit any call, regardless of its arguments or history.

Run from the repository root:

```sh
lake build LeanGuard.Experimental.TemporalRepair
(cd examples/dogwood && lake build && lake env lean Repairs.lean)
```

These contracts preserve the action and trusted evidence. A smaller transaction
requires permission from the user; policy compliance alone does not establish
that it fulfills their request. Missing approval, an expired grant, or a consumed
budget may require new trusted events before retrying. A failed candidate search
is not an impossibility proof. See the [repair guide](../repair/README.md).
