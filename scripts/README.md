# Repository tooling

Run these tools from the repository root after installing LeanGuard in editable
mode. They are development and evaluation utilities, excluded from the Python
wheel. The supported enforcement interfaces are in `python/leanguard/`.

| Location | Purpose |
| --- | --- |
| `python/leanguard/` | Native engine client, durable host, public adapter contract, CLI and optional integrations |
| `LeanGuard/` | Formal policy DSL, evaluators, domain policies and proofs |
| `scripts/verify.py` | Build, proof audit, lint, tests and native conformance gate |
| `scripts/release.py`, `scripts/check_install.py` | Verified wheel/source candidates and installed-artifact checks |
| `examples/custom_policy/` | Independent Lean package, safety contract, audit, and runtime/replay integration |
| `skills/leanguard-policy/` | Optional portable policy-authoring skill |
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

The gate uses ordinary Lake/Lean commands and excludes tests marked `live`. Ordinary
`pytest` runs also exclude them; `pytest -m live` explicitly selects model calls.
Tests for optional integrations skip when their dependencies are absent. Keep production
code independent of `scripts`, model clients and dataset loaders. New evaluation
utilities belong in `scripts/experiments/`; temporary analysis stays under an
ignored run directory. Keep reusable regression tests and maintained usage guides
in Git; keep downloaded datasets, journals, model weights and generated run reports
under ignored run directories.

## Article conformance

[Native policies](../LeanGuard/DogwoodExamples.lean) and
[trace fixtures](conformance.py) encode the
[Dogwood introduction](https://aws.amazon.com/blogs/opensource/introducing-dogwood-runtime-verification-for-ai-agents/).
Run `.venv/bin/python -m scripts.conformance` after `lake build`.
Forbid-only article snippets receive a base permit because LeanGuard defaults to
deny. The fixtures use whole dollars; benchmark adapters use integer cents.
Sale approvals require a real successful `ApproveSale` output with `approved = true`
and matching historical inputs. That backend must consult a trusted approval
authority. These approvals are reusable for one hour and correlated by principal;
the library's `confirmed` helper is single-use and conversation-bound.
The runner checks published expected verdicts, not cross-engine equivalence.
See the [DSL](../docs/native-dsl.md) for query semantics and the
[guarantee boundary](../docs/guarantees.md) for partial-history and live-admission limits.

## Optional τ² integration and experiments

The benchmark revision is
[`672227c6b6676edc20d57ea53b7000262aae77b9`](https://github.com/sierra-research/tau2-bench/tree/672227c6b6676edc20d57ea53b7000262aae77b9).
The `tau` extra installs the adapter's schema validator; the pinned benchmark and
its data must be installed separately. Use an editable checkout to retain its
data files and allow revision checks:

```sh
git clone https://github.com/sierra-research/tau2-bench.git .tau2
git -C .tau2 checkout 672227c6b6676edc20d57ea53b7000262aae77b9
.venv/bin/pip install -e '.[tau]' -e .tau2
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
`--help`, except conformance, which directly runs the fixed native checks. See the
[experiment guide](experiments/README.md) for local model evaluation, scoring and
external playback commands and limits.
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

## Release candidates

During dogfooding the package version is `0.2.0rc1` (Lean/Lake: `0.2.0-rc1`).
The release builder rejects stable version strings. It builds local candidates and
never uploads to PyPI, creates GitHub releases, or changes Git history.

```sh
.venv/bin/pip install -e '.[test,mcp,release]'
.venv/bin/python scripts/release.py
```

Start from a reviewed, committed checkout. `--allow-dirty` is available for local
packaging development and marks provenance accordingly. Output goes to ignored
`dist/` by default. The builder runs the verification gate, then produces a Python
source distribution, a platform wheel containing the native executable, and a
portable skill archive. The wheel includes exact build/dependency revisions,
executable/audit hashes, proof reports, and third-party license notices. The source
distribution includes Lean sources and the downstream example; source installs still
require a Lake build or an explicitly configured native executable.

The manually triggered [candidate workflow](../.github/workflows/release.yml) builds
on native Linux x86-64 and ARM64 runners inside manylinux containers, repairs/checks
wheel compatibility, and tests installation outside the checkout without Lean on the
runtime path. It also creates Lake build archives. Artifacts are candidates, with no
automatic publication. macOS and Windows are not advertised as supported platforms.

For a local wheel test, install the candidate into a fresh environment and run the
check from a directory outside the repository:

```sh
python3.12 -m venv /tmp/leanguard-consumer
/tmp/leanguard-consumer/bin/pip install /absolute/path/to/candidate.whl
cd /tmp
/tmp/leanguard-consumer/bin/python /absolute/path/to/LeanGuard/scripts/check_install.py
```

`LEANGUARD_BINARY` must be unset for this test. The check verifies the bundled binary,
actual denial/admission effects, approval consumption via replay, and recovery. The
candidate CI also runs the downstream source project and rejection tests for custom
axioms/unfinished proofs through the ordinary gate.

LeanGuard code, documentation, examples, and its skill use the root MIT license.
Dependencies retain their own terms. The pinned LeanLTL fork and upstream currently
lack a declared license: clarify redistribution permission before publishing binary
candidates. Generated notices identify this gap rather than relicensing third-party
code. After permission is established and candidates pass dogfooding, publish only
explicitly reviewed artifacts; any initial GitHub release should be marked as a
prerelease. PyPI release-candidate version strings remain prereleases.

A policy author installs the skill by copying/extracting `leanguard-policy` into their
coding agent's skill directory. Runtime consumers need only a compatible host and
compiled policy. Lake authors can use a pinned Git dependency; attach the platform's
`LeanGuard-<target>.tar.gz` archive to a matching GitHub prerelease to enable Lake's
release-build cache. Cached builds are specific to the source/toolchain/platform;
keep the audited sources available for independent rebuilding.
