# Repository tooling

Run these tools from the repository root after installing LeanGuard in editable
mode. They are development and evaluation utilities, excluded from the Python
wheel. The supported enforcement interfaces are in `python/leanguard/`.

| Location | Purpose |
| --- | --- |
| `python/leanguard/` | Native engine client, durable host, public adapter contract, CLI and optional integrations |
| `LeanGuard/` | Formal policy DSL, evaluators, domain policies and proofs |
| `scripts/verify.py` | Build, proof audit, lint, tests and native conformance gate |
| `scripts/emit_schemas.py` | Generate schemas from trusted benchmark tool definitions |
| `scripts/conformance.py` | Native evaluation of the documented Dogwood examples |
| `scripts/experiments/` | Local model benchmarks, dataset ingestion, playback and scoring |
| `tests/experiments/` | Regression tests for evaluation tooling |
| `runs/`, `private/` | Ignored local artifacts and scratch analysis; not library source |

## Verification

```sh
.venv/bin/pip install -e '.[test,mcp]'
.venv/bin/python scripts/verify.py
```

The gate uses ordinary Lake/Lean commands and makes no model calls. Tests for
optional integrations skip when their dependencies are absent. Keep production
code independent of `scripts`, model clients and dataset loaders. New evaluation
utilities belong in `scripts/experiments/`; temporary analysis stays under an
ignored run directory. Store reusable regression tests and concise results in Git,
not downloaded datasets, journals, model weights or generated run outputs.

## Optional τ² integration and experiments

The benchmark revision is
[`672227c6b6676edc20d57ea53b7000262aae77b9`](https://github.com/sierra-research/tau2-bench/tree/672227c6b6676edc20d57ea53b7000262aae77b9).
Use an editable checkout to retain its data files and allow revision checks:

```sh
git clone https://github.com/sierra-research/tau2-bench.git .tau2
git -C .tau2 checkout 672227c6b6676edc20d57ea53b7000262aae77b9
.venv/bin/pip install -e .tau2 'jsonschema>=4.20'
.venv/bin/pytest -q tests/test_tau.py
.venv/bin/pip install -e '.[experiments]'
.venv/bin/pytest -q tests/experiments
```

Ordinary tests need no model credentials or paid calls. Live model tests remain
explicitly opt-in. These experiments use instrumented current text-domain tasks;
they are not an unmodified historical τ² leaderboard run.

| Command prefix | Purpose |
| --- | --- |
| `python -m scripts.experiments.benchmark` | Run paired local-model episodes |
| `python -m scripts.experiments.score_saved` | Score saved episodes and verify native journals |
| `python -m scripts.experiments.trajectory_replay` | Download, normalize and audit external rollouts |
| `python -m scripts.experiments.trajectory_verify` | Independently recheck saved native decisions |
| `python -m scripts.experiments.serve_qwen35` | Launch the pinned local Qwen container |
| `python -m scripts.experiments.probe_throughput` | Measure local inference throughput |
| `python -m scripts.conformance` | Check native article-example conformance |

Use `.venv/bin/python` for the commands above. Their argument parsers support
`--help`, except conformance, which directly runs the fixed native checks. See
[local model evaluation](../docs/local-benchmark.md) and
[external playback](../docs/external-rollouts.md) for complete commands and limits.
The model launcher accepts `--cache`; its default respects `HF_HUB_CACHE`, then
`HF_HOME`, then the current user's Hugging Face cache.

## Command migration

The former `python -m leanguard.benchmark`, `leanguard.score_saved`, and
`leanguard.trajectory_*` commands now use the `scripts.experiments` namespace.
`leanguard.conformance` moved to `scripts.conformance`. The former `replay` extra
is now `experiments`, with the tooling dependencies declared together. Experiment
helpers `batch` and `rollout` moved with their callers. Public host and engine
imports and the `leanguard` CLI remain compatible.

Historical artifacts retain their original commands and source hashes. Check out
their recorded revision to reproduce that exact implementation; the layout change
does not rewrite old experiment results. The over-refusal fixes before this move
are preserved in commit `44196c6`.
