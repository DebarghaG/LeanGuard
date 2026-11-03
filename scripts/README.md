# Repository tooling

This directory holds the tools you need when working on LeanGuard itself: the
verification gate, the release builder, the Dogwood conformance runner and the
model experiments. None of it ships in the Python wheel. If you are integrating
LeanGuard into an application, everything you need lives in `python/leanguard/`.

Run these commands from the repository root after an editable install
(`bash scripts/setup.sh` does this for you).

| Location | What it is |
| --- | --- |
| `python/leanguard/` | The installed package: native engine client, durable host, adapter contract, CLI and optional integrations |
| `LeanGuard/` | The Lean policy DSL, evaluators, domain policies and proofs |
| `scripts/verify.py` | The verification gate: Lean build, proof audit, lint, tests and conformance |
| `scripts/release.py`, `scripts/check_install.py` | Build release candidates and check an installed wheel |
| `scripts/setup.sh` | Install pinned dependencies, build the runtime and run the demo |
| `scripts/emit_schemas.py` | Generate Lean schema declarations from the benchmark's tool definitions |
| `scripts/gen_a2a_grpc.py` | Regenerate the A2A gRPC stubs in `python/leanguard/a2a_grpc` from the vendored `a2a.proto` |
| `scripts/conformance.py` | Run the Dogwood article examples through the native engine |
| `scripts/experiments/` | Local model benchmarks, dataset import, replay and scoring |
| `examples/custom_policy/` | A standalone Lean package with its own safety proof, audit and Python integration |
| `skills/leanguard-policy/` | An optional policy-authoring skill for coding agents |
| `tests/experiments/` | Regression tests for the experiment tooling |
| `runs/`, `private/` | Git-ignored space for local artifacts and scratch analysis |

## Verification

Before sending a change, run the gate:

```sh
.venv/bin/pip install -e '.[test,mcp]'
.venv/bin/python scripts/verify.py
```

It uses plain Lake and Lean commands, so there is no extra tooling to install.
Tests for optional integrations skip themselves when their dependencies are
missing. Tests marked `live` call a model, so both the gate and a bare `pytest`
leave them out; select them explicitly with `pytest -m live`.

A few conventions keep the library separate from the research code. Production
code must not import from `scripts`, model clients or dataset loaders. New
evaluation utilities go in `scripts/experiments/`. Commit reusable regression
tests and maintained guides; keep downloaded datasets, journals, model weights,
generated reports and one-off analysis in an ignored run directory.

## Article conformance

AWS's [Dogwood introduction](https://aws.amazon.com/blogs/opensource/introducing-dogwood-runtime-verification-for-ai-agents/)
walks through a set of example policies and traces. LeanGuard encodes them as
[native policies](../LeanGuard/DogwoodExamples.lean) and checks them against
[trace fixtures](conformance.py). After `lake build`, run:

```sh
.venv/bin/python -m scripts.conformance
```

The runner checks that LeanGuard reproduces the article's published verdicts.

A few details differ from the article's presentation. LeanGuard denies by
default, so snippets that contain only a `forbid` rule get a base permit. The
fixtures count whole dollars, while the benchmark adapters use integer cents.

A sale is approved only by a real,
successful `ApproveSale` response whose output has `approved = true` and whose
inputs match. The backend behind `ApproveSale` must therefore consult a trusted
approval authority. To follow the article, these approvals are reusable for an
hour and correlated by principal. The library's own `confirmed` helper is
stricter: each approval works once, within one conversation.

Query semantics are covered in the [DSL guide](../docs/native-dsl.md), and what
partial histories can and can't tell you is covered in the
[guarantee boundary](../docs/guarantees.md).

## Optional τ² integration and experiments

The benchmark adapters target τ²-bench at revision
[`672227c6b6676edc20d57ea53b7000262aae77b9`](https://github.com/sierra-research/tau2-bench/tree/672227c6b6676edc20d57ea53b7000262aae77b9).
The `tau` extra installs only the adapter's schema validator; you install the
benchmark yourself. Use an editable checkout so its data files stay in place and
the revision check can find them:

```sh
git clone https://github.com/sierra-research/tau2-bench.git .tau2
git -C .tau2 checkout 672227c6b6676edc20d57ea53b7000262aae77b9
.venv/bin/pip install -e '.[tau]' -e .tau2
.venv/bin/pytest -q tests/test_tau.py
.venv/bin/pip install -e '.[experiments]'
.venv/bin/pytest -q tests/experiments
```

None of these tests need model credentials or make paid calls. The experiments
run instrumented versions of the current text-domain tasks, so their numbers
can't be compared with the historical τ² leaderboard.

| Command | Purpose |
| --- | --- |
| `python -m scripts.experiments.benchmark` | Run paired local-model episodes |
| `python -m scripts.experiments.score_saved` | Score saved episodes and recheck native journals |
| `python -m scripts.experiments.trajectory_replay` | Download, normalize and audit published rollouts |
| `python -m scripts.experiments.trajectory_verify` | Recheck saved native decisions independently |
| `python -m scripts.experiments.serve_qwen35` | Launch the pinned local Qwen container |
| `python -m scripts.experiments.probe_throughput` | Measure local inference throughput |
| `python -m scripts.conformance` | Check the Dogwood article examples |

Run them with `.venv/bin/python`. Every command except `conformance`, which has
no options, accepts `--help`. The model launcher's `--cache` flag defaults to
`HF_HUB_CACHE`, falling back to `HF_HOME` and then your user's Hugging Face
cache. The [experiment guide](experiments/README.md) covers the full workflow.

Saved experiment artifacts record the commands and source hashes that produced them;
to reproduce one exactly, check out its recorded revision.

## Release candidates

While LeanGuard is being dogfooded, the package version is `0.2.0rc2` (written
`0.2.0-rc2` for Lean and Lake). The release builder produces local candidates
only: it refuses stable version strings, and it never uploads to PyPI, creates a
GitHub release or touches Git history.

```sh
.venv/bin/pip install -e '.[test,mcp,release]'
.venv/bin/python scripts/release.py
```

Start from a reviewed, committed checkout. For packaging work you can pass
`--allow-dirty`, which records the dirty state in the provenance. The builder
runs the verification gate first, then writes three artifacts to the ignored
`dist/` directory (change it with `--output`):

- a Python source distribution, containing the Lean sources and the downstream
  example. Installing it still needs a Lake build or an explicitly configured
  native executable.
- a platform wheel with the native executable bundled, plus exact build and
  dependency revisions, executable and audit hashes, proof reports and
  third-party license notices.
- a portable archive of the policy-authoring skill.

The manually triggered [candidate workflow](../.github/workflows/release.yml)
does the same on native Linux x86-64 and ARM64 runners inside manylinux
containers. It repairs and checks wheel compatibility, installs the wheel
outside the checkout to confirm it runs without Lean, and produces Lake build
archives. Nothing is published automatically. macOS and Windows are not
supported platforms.

To test a wheel yourself, install it into a fresh environment and run the check
from outside the repository, with `LEANGUARD_BINARY` unset:

```sh
python3.12 -m venv /tmp/leanguard-consumer
/tmp/leanguard-consumer/bin/pip install /absolute/path/to/candidate.whl
cd /tmp
/tmp/leanguard-consumer/bin/python /absolute/path/to/LeanGuard/scripts/check_install.py
```

The check confirms that the bundled binary is used, that denials and admissions
have the expected effects, that replay shows the approval consumed, and that
recovery works. In CI, the ordinary gate also builds the downstream source
project and confirms that custom axioms and unfinished proofs are rejected.

During dogfooding, publish reviewed artifacts as GitHub prereleases; on PyPI,
release-candidate version strings are treated as prereleases too. LeanGuard's
code, documentation, examples and skill are under the root MIT license, and
dependencies keep their own terms.

How each audience consumes a release:

- Policy authors install the skill by copying or extracting `leanguard-policy`
  into their coding agent's skill directory.
- Runtime consumers need only a compatible host and a compiled policy.
- Lake users can depend on a pinned Git revision. Attaching the platform's
  `LeanGuard-<target>.tar.gz` archive to the matching GitHub prerelease enables
  Lake's release-build cache. Those cached builds are tied to one source
  revision, toolchain and platform, so keep the audited sources available for
  anyone who wants to rebuild.
