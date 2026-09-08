# External rollout results — 2026-09-08 UTC

All four requested datasets were downloaded at immutable revisions and replayed
through the LeanLTL-integrated native LeanGuard binary. This is a fixed-trajectory
policy audit; published model rewards are preserved and are not counterfactual
success scores after blocking. See the [method and reproduction commands](external-rollouts.md).

**5,459 replay units; 46,791 assistant calls; 178,384 native rule evaluations.**
Every saved native response was independently re-executed and matched exactly.
All normalized assistant calls and all replay units are accounted for. No model
inference or environment tool execution was needed.

## Call-level results

Each assistant call appears in exactly one category. Policy failures can coexist
with missing evidence on the same call; the complete rule results are retained.

| Dataset/domain | Units | Calls | Allow | Policy failure | Evidence missing | Unsupported | Invalid arguments |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Snorkel airline | 500 | 5,831 | 1,225 | 27 | 871 | 3,708 | 0 |
| Snorkel verified airline | 996 | 14,085 | 1,930 | 659 | 2,725 | 8,771 | 0 |
| fuvty retail | 1,000 | 4,277 | 2,008 | 90 | 2,169 | 8 | 2 |
| fuvty airline | 464 | 1,538 | 388 | 890 | 59 | 201 | 0 |
| AReaL retail | 1,000 | 7,593 | 2,899 | 49 | 4,644 | 0 | 1 |
| AReaL airline | 999 | 10,385 | 4,507 | 15 | 5,850 | 13 | 0 |
| AReaL telecom | 500 | 3,082 | 2,445 | 9 | 612 | 16 | 0 |
| **Total** | **5,459** | **46,791** | **15,402** | **1,739** | **16,930** | **12,717** | **3** |

There are 653 replay units with at least one recorded failed policy rule, including
530 with a published success label. These are **policy disagreements to inspect**,
not a measured false-positive rate. Most fuvty airline disagreements concern its
identity workflow; the dataset exposes identity lookup tools outside the pinned
LeanGuard airline interface. Some Snorkel traces repeatedly pass malformed user-ID
strings, which the ownership rule catches. The datasets' policies, tool behavior,
and success labels do not all match the pinned policy pack.

## Findings relevant to over-refusal

The `retail.modify_once` rule fails on **135 calls**. In 96 cases, an item update
follows an address update on the same order; in another 19, it follows a payment
update. The benchmark tools accept these sequences and return successful results
in 128 of the 135 cases; the other seven have no stored outcome. LeanGuard's
current interpretation reserves one modification across all three actions.

The pinned retail policy has a broad once-per-order sentence in its generic action
rules and a more specific once-only item-change section. Its tools leave the order
pending after address/payment changes and permit a subsequent item change.
This is a material **policy-interpretation versus tool-behavior disagreement**:
LeanLTL correctly evaluates the selected stricter rule. It is not evidence that
incorporating LeanLTL changed executable semantics. The native rule was kept fixed
throughout this external evaluation and the concurrent Qwen experiment.

There are also **nine payment-request denials** where the observed telecom bill
status is `Issued`, while LeanGuard requires `Overdue`. All nine recorded tool calls
succeeded. The upstream tool validates ownership and absence of another awaiting
payment but does not require the `Overdue` status. Again, tool success alone does
not establish compliance with the chosen formal policy.

## Coverage limits

The replay exercises **39 of the 43 supported domain/tool pairs**, including 31,839
airline calls, 11,870 retail calls, and 3,082 telecom calls when unsupported calls
are included. The four absent supported tools are retail `get_item_details` and
`list_all_product_types`, and telecom `suspend_line` and `disable_roaming`.

The 12,717 unsupported calls include **12,149 `code_evaluation` calls**. Arbitrary
Python database access is outside the existing named-tool policy surface and was
never executed. These default denials are reported separately from named-tool
policy failures.

The 16,930 evidence-only denials include first reads whose hidden ownership facts
are not available in the recorded prefix, missing bound approvals, incomplete
state after writes, and absent simulator travel evidence. They are not labeled as
proven bad actions. There are 105 missing/ambiguous recorded outcomes and zero
orphan responses; 8,661 user-tool calls are preserved as user-role observations
rather than being misclassified as assistant calls.

All 4,270 fuvty training prefixes are contained in its 1,464 complete rollouts.
AReaL's 33,531 training rows reduce to 2,499 maximal prefixes without divergent
branches. The 2,262 task-definition rows are accounted for but contain no execution
to audit. Downloaded reward-verification code and hidden task solutions are unused.

## Validation and artifacts

- Full Python suite: **151 passed, 6 optional live tests skipped**.
- Twelve dedicated replay tests include native temporal behavior, batch ordering,
  no future-result leakage, identity timing, missing confirmations, unsupported
  code isolation, incomplete observations, stale state after mutation failures,
  user/assistant separation, and corrupted export detection.
- Full Python lint and whitespace checks pass.
- All 46,791 native audit responses rechecked identically, covering 178,384 rule
  evaluations. The Lean sources and native binary were not changed by this replay.

The replay artifacts are in `runs/external-rollouts-20260908/full-replay-v3/`.
`episode-scores.csv` has one row for every replay unit, its original reward, and
allow/failure/evidence/unsupported counts. `calls.jsonl` retains each individual
verdict; `native-audits.jsonl.gz` retains each exact native context and response.
The concise machine-readable aggregate is checked in alongside this report.

Native binary SHA-256:

```
fe01113168a89a960f63a8d054d0ed6628dceca78258fef06b2300d043a77a3a
```

The [LeanLTL correspondence theorems](leanltl.md) establish the native policy
meaning for supplied contexts. This empirical run does not prove the Python
importer or resolve ambiguities in English benchmark policies. It is separate
from the ongoing real Qwen3.5-4B 200-episode experiment.
