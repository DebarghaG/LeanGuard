# Dogwood guide examples in LeanGuard

[Dogwood](https://github.com/dogwood-policy/dogwood) is a runtime-verification
language for AI agents, and its guide contains 86 worked examples. This project
writes every one of them as a native LeanGuard policy, then runs both
implementations on the same traces to see whether they agree. It's a test of
whether LeanGuard's public API, as it stands, can express someone else's policy
language. It could: no LeanGuard changes were needed.

Everything here lives in a separate Lake project. None of these policies go into
LeanGuard's built-in registry, and there is no Dogwood parser: each example was
ported by hand.

The examples come from the
[Dogwood guide index](https://dogwood-policy.github.io/dogwood/examples/index.html),
pinned to [dogwood-policy/dogwood at c6237c8](https://github.com/dogwood-policy/dogwood/tree/c6237c88099b3f492ecc5fcee42df06a19224b97/dogwood-docs/examples).
The upstream bundles stay in their own Apache-2.0 checkout. The native
implementation, adapter and tests here are under LeanGuard's MIT license.

## How the examples are encoded

| Approach | Examples | What crosses into Lean |
| --- | ---: | --- |
| Native predicates and temporal operators | 65 | Normalized, typed event records |
| Extra data adapters | 10 | Entity type and membership, optional request context, a clock, or custom event kinds |
| Information-provider adapters | 11 | Typed results from trusted providers; the Rhai, regex or classifier behind them stays outside the proof |

84 of the 86 can be compared directly against the Dogwood interpreter. The other
two, `sell_after_2024_datetime` and `sell_datetime_window`, can't, because at the
pinned revision Dogwood's event `Value` type and log parser have no way to carry a
datetime: supplying an ISO timestamp fails with `expected datetime, got string`.
Both source policies validate, and neither has a published trace. The runner keeps
those errors in its report and checks the intended clock predicates on its own,
leaving the upstream engine unchanged. These two aren't counted as differential
successes.

## Run

Start from the LeanGuard repository root with the development Python environment
from the main README:

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

Rust is only needed to build Dogwood for comparison; the LeanGuard example binary and
the Python adapter never call it. The runner insists on a clean checkout at the pinned
revision, apart from the `Cargo.lock` and `target/` that the build generates. If you
want to reproduce the exact dependency resolution, keep that lockfile alongside your
reference build.

`run.py` validates every source bundle, checks each published trace against both the
original CLI and its `expected.out`, and then runs the generated scenarios in
`cases.py`. Expected verdicts are only ever compared against, never used to build a
native policy. The script exits nonzero on any unexpected disagreement or evaluation
error, and for the two clock examples it checks that the upstream limitation is still
there. If a run is interrupted, the report has no final `summary` field.

The results go to `results.json`, which git ignores. It records SHA-256 hashes of the
source files and binaries, a hash of each generated trace, decision counts, and every
disagreement. Temporary traces, upstream dependencies, binaries and raw reports are
kept out of the source distribution.

## Semantics that matter

Most disagreements you'd expect between two policy engines come down to a handful of
modeling choices. These are the ones this port makes.

- One line is one timepoint. Two events with the same timestamp are still two
  positions. `formerly` includes the current position, and windows include their
  endpoints. By default each history is projected to the principal before `previous`
  and `since` run. The two alert schemas that are explicitly unpinned, and the
  raised-window schema, keep the global history instead. Resource correlation is
  added only where the source asks for it.
- Logged data and the current request's context are kept apart. A historical
  response counts as a `success` record for matching, even if its output says
  `result: false`; only a policy that explicitly checks that output requires it to be
  true. Neither a response nor a request with "approval" in its name becomes a user
  confirmation, and denied requests and recorded outcomes both stay in the replayed
  history.
- Custom event kinds are mapped explicitly. Only the `login_attempt_custom_kind`
  schema maps `attempt` to a request and `outcome` to a response. The adapter rejects
  any other kind, and rejects records whose logged actor or resource disagrees with
  their scope.
- Aggregates count positions. A count is over positions, so repeated timestamps or
  amounts are counted again. Sums binding `(amount,timepoint)` keep repeated values
  and use signed integers, while the sum over current-only amounts deduplicates its
  values. Because these examples only compare sums against small bounds, exact integer
  totals and Dogwood's final signed 64-bit saturation give the same answer.
- Providers sit outside the proof. Small adapters reproduce the provider fixtures
  that ship with Dogwood and pass each result into Lean, where the policy combines them;
  Dogwood runs its original Rhai separately. So `Content::Risk` here is the source's
  fixed keyword lookup, standing in for a real content classifier. The regex adapter
  matches the whole string, which reproduces how Rust's `$` treats a trailing newline.
- The comparison covers a fixed domain. Each example uses its own finite action
  schema, typed Cedar Long inputs, integer-second timestamps and consistent scope
  fields. Decimal context values are exact signed numbers with four decimal places, and
  clocks are UTC milliseconds. The adapter doesn't parse general Cedar or validate entity
  stores, and the two languages' handling of malformed records and error recovery are
  not claimed to match.

Some source examples do less than their names or comments suggest, and the port keeps
them that way:

- `read_login_not_logout` only rules out a Logout at the current position, so a Logout
  that happened earlier doesn't cancel an earlier Login. A generated trace tests this.
- `temporal_login_then_read`, and its composed-macro counterpart, require both events
  within the hour but never require the Login to come before the Read.
- `write_after_read` actually gates SellShares on an ApproveSale response for the
  stock. It neither checks the approval's Boolean output nor consumes it.
- Seven examples deny every call when each timepoint holds a single event:
  `alert_heartbeat_and_login_rate`, `alert_login_current_tp`,
  `alert_total_transfer_over_200`, `read_heartbeat_since_login_30s`,
  `read_since_login`, `forbid_large_except_amzn` and
  `forbid_read_transfers_over_1000`. The first five need a second event or a
  current-only aggregate at the current position. The last two have no permit rule at
  all. Because default denial would hide a broken threshold or sum in those two, the
  runner also compares whether the forbid itself fires.

The point of the exercise is faithful representation, so these rules are ported as
written. They aren't recommendations for production guardrails.

## Proof scope

`lake build` checks `GuideAudit.lean`, which audits the runtime entry point and every
declaration in the imported LeanGuard and guide namespaces. The audit rejects
`sorryAx` and custom axioms, allowing only Lean's standard `propext`,
`Classical.choice` and `Quot.sound`.

`DogwoodGuide.sound` ties every encoded decision, error gate included, to its LeanLTL
meaning through `decision_leanLTL_correct`. `DogwoodGuide.access_witness` goes further
for the access example: an allowed access has a grant within the hour, and no matching
revocation at any later position in the principal's history. Replaying the published
access trace gives Grant: deny → Access: allow → Revoke: deny → Access: deny.

The theorems are about the encoded policies and the facts they're given. Agreement in
replay is test evidence that the hand ports are right. Equivalence to Dogwood's Rust
implementation, truthful logs, and correct provider results are all outside what's
proved; the [guarantee boundary](../../docs/guarantees.md) covers this in general.

## Repair experiments

[Repairs.lean](Repairs.lean) runs `guard_repair?` against full LeanLTL policy goals.
When the task allows a smaller positive sale, a sale of 100 shares is repaired to 99.
When the task requires exactly 100, the same file proves no allowed edit exists. It
also proves that the two forbid-only guide policies can never admit a call, whatever
its arguments or history.

Run it from the repository root:

```sh
lake build LeanGuard.Experimental.TemporalRepair
(cd examples/dogwood && lake build && lake env lean Repairs.lean)
```

These repair contracts keep the action and the trusted evidence fixed. Selling fewer
shares still needs the user's permission, since a policy-compliant call isn't
necessarily what they asked for. A missing approval, an expired grant or a spent
budget can only be fixed by new trusted events, after which the call can be retried.
When candidate search fails, all it shows is that none of the candidates worked. The
[repair guide](../repair/README.md) has the details.
