# LeanLTL integration validation — 2026-09-07

The integration passed the default Lean build and `scripts/verify.py`:

- Transitive axiom audit: 902 public LeanGuard declarations, allowing only
  `propext`, `Classical.choice`, and `Quot.sound`.
- 39 named safety-theorem axiom reports; 18 kernel-checked LeanLTL regression theorems.
- Python: 126 passed, 6 live tests skipped in the ordinary suite.
- Separate real-Qwen retry tests: all 6 passed.
- Python lint and formatting passed; Dogwood conformance passed all 21 traces and
  73 verdicts.
- Temporary negative controls using a custom axiom, `sorry`, and `native_decide`
  were each rejected by the axiom audit. The documentation's Lean examples compiled.

The real-model smoke run used the existing local Qwen3.5-4B server, with checkpoint
`851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`, and the pinned τ² checkout
`672227c6b6676edc20d57ea53b7000262aae77b9`. It selected one task per domain with
seed 300, testing baseline, generic denial, and actionable feedback. Thinking mode,
the existing sampling settings, 240-step limit, 1,800-second episode timeout,
32,768-token context, and 8,192-token generation allowance were retained.

```sh
.venv/bin/python scripts/verify.py
LEANGUARD_LIVE_TESTS=1 .venv/bin/pytest -q tests/test_rollout.py -k live_qwen_retry
.venv/bin/python -m leanguard.benchmark \
  --tasks-per-domain 1 --concurrency 9 \
  --output runs/qwen35-4b-leanltl-smoke-20260907
```

Use a new output directory when repeating the experiment.

| Domain/task | Baseline | Generic denial | Actionable feedback |
|---|---|---|---|
| Retail / 65 | Reward 1.0 | Protocol failure | Reward 1.0 |
| Airline / 43 | Reward 1.0 | Reward 1.0 | Protocol failure |
| Telecom / mobile data, hard persona | Context limit | Context limit | Context limit |

All nine episodes were attempted, with no unstarted episodes or circuit-breaker
halt. Wall time was 1,478.6 seconds. The benchmark runner returned exit status 1:
four episodes received a deterministic reward of 1.0 and five failed. The two
protocol failures exhausted the retry allowance for mixed text/tool-call outputs.
The three telecom runs exceeded the context limit after long conversations; their
terminal environment assertions were all satisfied, but the original runner stored no
task score for them. They remain failed episodes; the scoring pass below assigns zero
using the upstream premature-termination rule. All four scored episodes passed the benchmark's
replay-to-live-state consistency check.

The six guarded episodes recorded 36 assistant tool attempts, zero native denials,
and zero adapter errors. This smoke sample does not measure intervention quality
or establish an improvement over the earlier implementation. The formal guarantees
come from the Lean theorems, and the model/simulator limitations remain as described
in [the benchmark protocol](local-benchmark.md).

Full artifacts are retained locally under
`runs/qwen35-4b-leanltl-smoke-20260907/`: `report.json`, `validation-summary.json`,
`runner.log`, model request/response logs, conversations, journals, decisions,
confirmations, and final-state diagnostics. `verification/checks.json` records the
proof-source fingerprints, LeanLTL revision, and verification results; the test logs
and axiom-audit negative-control logs are alongside it. The source and compiled
policy fingerprints were checked against the actual benchmark manifest after the run.
The policy binary SHA-256 is
`fe01113168a89a960f63a8d054d0ed6628dceca78258fef06b2300d043a77a3a`.

Raw run artifacts remain ignored by Git. This document records the results without
committing simulated customer records or generated model conversations.

## Complete episode scoring

A subsequent scoring pass assigned a numeric deterministic reward to all nine saved
trajectories using the pinned upstream `evaluate_simulation` evaluator. The four
completed rewards stayed at 1.0. The two protocol failures and three context-limit
failures each received 0.0 under its premature-termination rule.

| Domain | Baseline | Generic denial | Actionable feedback |
|---|---:|---:|---:|
| Retail | 1.0 | 0.0 | 1.0 |
| Airline | 1.0 | 1.0 | 0.0 |
| Telecom | 0.0 | 0.0 | 0.0 |
| Mean | 66.7% | 33.3% | 33.3% |

Overall: **4/9 (44.4%)**; the two guarded modes together: **2/6 (33.3%)**.
All 229 commands and 36 admission decisions from the six guarded journals reproduced
exactly through the current LeanGuard binary. The complete scorecard, CSV, scoring
procedure, and per-episode reward details are saved under the run's
`all-episode-scores/` directory. The original run artifacts were not overwritten.
