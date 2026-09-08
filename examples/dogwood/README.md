# Dogwood guide dogfooding

This separate Lake project encodes all **86** examples in the
[Dogwood guide index](https://dogwood-policy.github.io/dogwood/examples/index.html)
using LeanGuard's existing public APIs. It does not add policies to the production
registry or implement a Dogwood language frontend.

Source: [dogwood-policy/dogwood at c6237c8](https://github.com/dogwood-policy/dogwood/tree/c6237c88099b3f492ecc5fcee42df06a19224b97/dogwood-docs/examples).
The website and checkout contained the same 86 example names on 2026-09-08.
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
of each generated trace, decision counts, and every disagreement. The coverage
table below is a compact record of the completed run. Temporary traces, upstream
dependencies, binaries and raw reports are excluded from source distribution.

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

## Completed coverage

The table is populated from the completed report after validation. `N` means
native, `D` a data adapter and `P` a provider adapter. A dash means the source
does not supply a trace. Clock rows use the independent oracle described above.

Run on 2026-09-08: **192/192 published decisions matched** across 49 traces.
The 6,670 generated decisions comprise **6,656/6,656 Dogwood comparisons**
and **14/14 independent clock checks**. There were zero unexpected errors
or disagreements. The 647-declaration axiom audit and nine adapter tests passed.

| Example | Approach | Published decisions | Generated decisions | Result |
| --- | :---: | ---: | ---: | --- |
| `access_not_revoked_since_grant` | N | 4 | 40 | Matched |
| `alert_exactly_three_transfers` | N | 8 | 22 | Matched |
| `alert_heartbeat_and_login_rate` | N | 6 | 42 | Matched |
| `alert_login_and_big_transfer` | N | — | 35 | Matched |
| `alert_login_current_tp` | N | — | 16 | Matched |
| `alert_login_in_last_hour` | N | 3 | 34 | Matched |
| `alert_pending_transfers` | N | — | 20 | Matched |
| `alert_same_principal_login_transfer` | N | — | 35 | Matched |
| `alert_same_user_login_and_transfer` | N | 7 | 35 | Matched |
| `alert_some_login` | N | 4 | 34 | Matched |
| `alert_total_transfer_over_200` | N | 6 | 19 | Matched |
| `allow_anything` | N | — | 136 | Matched |
| `approve_has_output_guard` | D | — | 140 | Matched |
| `call_cedar_macro_as_argument` | N | — | 136 | Matched |
| `call_cedar_macro_is_small` | N | — | 136 | Matched |
| `call_cedar_macro_with_temporal_leaf` | N | 5 | 34 | Matched |
| `call_cedar_macros_composed` | N | — | 136 | Matched |
| `call_temporal_aggregation_macro_count` | N | 5 | 34 | Matched |
| `call_temporal_condition_macro_once` | N | 3 | 69 | Matched |
| `call_temporal_condition_macros_composed` | N | 5 | 56 | Matched |
| `cedar_eligible_not_blocked` | N | — | 136 | Matched |
| `cedar_is_small_threshold` | N | — | 136 | Matched |
| `cedar_macro_plus_temporal_leaf` | N | 4 | 34 | Matched |
| `cedar_semver_gt` | N | — | 136 | Matched |
| `cedar_starts_with_f_like` | N | — | 136 | Matched |
| `cedar_within_cap_if_else` | N | — | 136 | Matched |
| `cond_is_oauth_in_team` | D | — | 13 | Matched |
| `deny_overrides_sell_not_amzn` | N | 3 | 136 | Matched |
| `forbid_large_except_amzn` | N | 3 | 136 | Matched |
| `forbid_read_transfers_over_1000` | N | 5 | 39 | Matched |
| `get_amzn_stock_info` | N | 2 | 136 | Matched |
| `heartbeat_scope_alias` | N | 3 | 58 | Matched |
| `login_attempt_custom_kind` | D | 3 | 52 | Matched |
| `macro_library_once_is_small` | N | 4 | 156 | Matched |
| `max_window_raised` | N | — | 43 | Matched |
| `permit_read_anyone` | N | 3 | 2 | Matched |
| `principal_is_oauth` | D | — | 139 | Matched |
| `provider_allowed_or_short` | P | 4 | 23 | Matched |
| `provider_digitcount_forbid` | P | 4 | 23 | Matched |
| `provider_digitcount_operator_ge` | P | 4 | 23 | Matched |
| `provider_filter_set_index_decimal` | P | 3 | 23 | Matched |
| `provider_int_arithmetic_trusted` | P | 4 | 25 | Matched |
| `provider_matches_and_not_blocked` | P | 3 | 23 | Matched |
| `provider_principal_id_allowlist` | P | 2 | 23 | Matched |
| `provider_regex_analyze_fields` | P | 4 | 23 | Matched |
| `provider_regex_matches_uppercase` | P | 3 | 23 | Matched |
| `provider_risk_decimal_method` | P | 3 | 23 | Matched |
| `read_after_login` | N | 3 | 14 | Matched |
| `read_after_login_success` | N | 2 | 43 | Matched |
| `read_heartbeat_since_login_30s` | N | 7 | 34 | Matched |
| `read_login_not_logout` | N | 4 | 46 | Matched |
| `read_prev_compute_open_session` | N | — | 39 | Matched |
| `read_prev_login` | N | 3 | 50 | Matched |
| `read_prev_login_success` | N | 3 | 43 | Matched |
| `read_since_login` | N | 5 | 39 | Matched |
| `sell_after_2024_datetime` | D | — | 7 | Clock oracle only |
| `sell_after_approval_valid_ticker` | P | 5 | 148 | Matched |
| `sell_comparison_chain` | N | — | 136 | Matched |
| `sell_datetime_window` | D | — | 7 | Clock oracle only |
| `sell_like_a_prefix` | N | 3 | 136 | Matched |
| `sell_logical_grouping` | N | — | 136 | Matched |
| `sell_nested_if_threshold` | N | — | 136 | Matched |
| `sell_nonzero_proceeds_decimal` | D | — | 148 | Matched |
| `sell_not_blocked_string` | N | — | 136 | Matched |
| `sell_not_test_tickers_like` | N | — | 136 | Matched |
| `sell_or_approve_action_in` | N | — | 136 | Matched |
| `sell_shares_eq_scope` | N | — | 136 | Matched |
| `sell_shares_temporal_subexpr` | N | 2 | 156 | Matched |
| `sell_small_only` | N | 3 | 136 | Matched |
| `sell_small_proceeds_decimal_method` | D | — | 148 | Matched |
| `sell_threshold_by_stock` | N | 4 | 136 | Matched |
| `sell_two_when_small_amzn` | N | — | 136 | Matched |
| `sell_unless_huge` | N | — | 136 | Matched |
| `sell_when_under_100` | N | — | 136 | Matched |
| `sell_when_unless_mix` | N | — | 136 | Matched |
| `sell_zero_proceeds_if_has` | D | — | 148 | Matched |
| `simplest_permit` | N | — | 136 | Matched |
| `submit_after_approval_injection` | N | 5 | 24 | Matched |
| `temporal_count_formerly_login` | N | 3 | 34 | Matched |
| `temporal_login_then_read` | N | 5 | 56 | Matched |
| `temporal_once_read_recent` | N | 3 | 78 | Matched |
| `temporal_sum_formerly_transfer` | N | 4 | 43 | Matched |
| `traders_is_in_group_scope` | D | — | 13 | Matched |
| `transfer_prev_nested_conj` | N | — | 30 | Matched |
| `write_after_read` | N | 3 | 148 | Matched |
| `write_after_read_formerly` | N | 5 | 69 | Matched |
