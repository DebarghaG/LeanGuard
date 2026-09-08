# Evaluation tooling

These repository scripts run local-model experiments and audit saved trajectories.
Follow the [tooling setup](../README.md) for the pinned editable τ² checkout and
optional dependencies, and build the native engine with `lake build`. Run commands
below from the repository root. Dataset and model revisions are pinned in the
scripts; generated artifacts belong under the ignored `runs/` directory.

## Local model evaluation

The runner uses the pinned retail, airline and telecom `base` splits. The agent and
simulated customer receive the normal domain prompts and tools. Expected actions,
scoring assertions and gold databases are used only for scoring.

[serve_qwen35.py](serve_qwen35.py) pins the Qwen3.5-4B checkpoint and an ARM64 vLLM
Docker image. It requires Docker, GPU access and the cached model snapshot. Preview
the launch command:

```sh
.venv/bin/python -m scripts.experiments.serve_qwen35 \
  --name leanguard-qwen35-4b --max-num-seqs 16 --prefix-caching --print-command
```

Run it again without `--print-command` to start the server. Use `--cache` to select
a Hugging Face cache. The launcher serves BF16 on GPU 0 with a 32,768-token context,
a 20% GPU-memory budget and a loopback-only endpoint at port 18000. Check its
hardware and image assumptions before using a different machine.

Once the server is ready, run paired episodes and score every attempted episode:

```sh
.venv/bin/python -m scripts.experiments.benchmark \
  --total-tasks 100 --modes baseline generic --concurrency 12 \
  --output runs/qwen35-4b-evaluation
.venv/bin/python -m scripts.experiments.score_saved runs/qwen35-4b-evaluation
```

This selects 100 distinct tasks without replacement: 41 retail, 18 airline and 41
telecom. Each runs once with the baseline and once with generic LeanGuard denial,
giving 200 episodes. Use `--total-tasks 278` for all base tasks and 556 paired
episodes. Output directories must be new. The optional `guarded` mode supplies
actionable feedback; specify `--modes baseline generic` to exclude that arm.
`--total-tasks` and `--tasks-per-domain` are mutually exclusive. Use `--help` for
sampling and resource controls; endpoints must remain local.

### Execution and consent boundaries

Native policies are fixed. Assistant calls go through `GuardHost`; customer tools
keep their separate role. A separate Qwen call simulates a trusted confirmation UI,
using the canonical proposal, visible dialogue and completed tool outcomes. Hidden
customer scenarios are not supplied to that check. Pending questions, withdrawals
and unmet prerequisites do not authorize a mutation. Malformed or unavailable
approval fails closed; only timeout or exhausted-output failures get one retry.
A valid denial is final and both attempts are recorded.

This simulated UI is an unverified consent authority: a model mistake can mint
incorrect approval evidence. It cannot establish that the actor understood consent.
Production integrations need independently authorized, structured confirmation;
see the [guarantee boundary](../../docs/guarantees.md).

Airline identity requires an unambiguous literal user ID in customer messages.
Cancellation reasons use narrow matching of customer-originated text; negated or
ambiguous reasons fail closed. Telecom travel evidence comes from the live
simulator sensor for the authenticated customer's line. These adapters do not
prove general language understanding, and missing evidence can block a feasible
task. See [coverage and interpretations](../../docs/coverage.md).

All modes share protocol controls: invalid empty, mixed text/tool or multi-tool
generations are rejected before dispatch and retried once in non-thinking mode.
Exhaustion fails the episode. Reasoning text never becomes a tool call. Customer
tool-loop and handoff interventions are logged and do not consult task solutions.
The default cap is 240 steps and 1,800 seconds per episode; an in-flight request
has its own 600-second timeout and can exceed the episode deadline. History is
not silently truncated to fit the server context. Three classified integration
errors halt scheduling by default; unstarted episodes are reported separately.

### Scores and artifacts

The manifest records task IDs and contents, seeds, source and binary fingerprints,
benchmark revision and serving configuration. Runs retain conversations, request
logs and per-episode results. Guarded runs also retain native journals, decisions,
simulated confirmations and denial checkpoints. Usage includes returned rejected
generations and retries; transport failures can leave token accounting incomplete.
Seeds do not guarantee identical output across GPU batching schedules.

Deterministic scores use the pinned upstream evaluators but exclude natural-language
assertions. Local Qwen judgments produce a separate combined score subject to
self-judge bias. Neither score proves full English-policy compliance. Attempted
episode failures remain in the denominator; unstarted episodes remain separate.

The upstream scorer re-executes mutations. The scoring copy excludes only calls
that the host did not dispatch, plus their paired responses; the original trace
retains every denial. Dispatched calls that failed are retained. Scoring replay
must reproduce both live agent and user database hashes before a score is accepted.

`score_saved` checks report coverage, task contents, artifacts and the binary and
benchmark fingerprints. It rechecks native journals without dispatching tools,
and uses the upstream evaluator to check task rewards. Premature terminations and
failed live-state checks receive conservative zero rewards in the all-attempts
result, with upstream diagnostics retained separately. It writes JSON/CSV sidecars
under `all-episode-scores/` and refuses to overwrite existing results.

Repeated-denial and recovery metrics are observational: a later admission does not
prove semantic repair. Saved checkpoints do not implement counterfactual branches.
These instrumented local self-play experiments are not official leaderboard scores
or controlled measurements of serving throughput. Live protocol tests are opt-in:

```sh
.venv/bin/pytest -q -m live tests/experiments/test_rollout.py
```

## External rollout replay

Download the pinned datasets, audit every normalized conversation and independently
recheck the saved native decisions:

```sh
.venv/bin/python -m scripts.experiments.trajectory_replay \
  runs/external-rollouts --download --output runs/external-rollouts/full
.venv/bin/python -m scripts.experiments.trajectory_verify \
  runs/external-rollouts runs/external-rollouts/full
```

Omit `--download` to reuse snapshots. Omit `--limit` to process all conversations.
Output directories must be new. [trajectory_data.py](trajectory_data.py) pins:

- [Snorkel airline](https://huggingface.co/datasets/snorkelai/Tau2-Bench-Airline-With-Code-Agents).
- [Snorkel verified airline](https://huggingface.co/datasets/snorkelai/Tau2-Bench-Verified-Airline-With-Code-Agents).
- [fuvty synthetic](https://huggingface.co/datasets/fuvty/tau-bench-synthetic).
- [AReaL τ²](https://huggingface.co/datasets/inclusionAI/AReaL-tau2-data).

Full rollouts and maximal conversation prefixes are replay units. Prefix matching
uses roles, content, error metadata and tool arguments, ignoring regenerated call
IDs; divergent branches are retained. Task definitions are accounted for separately
because they contain no execution history. Training rows are not each counted as
independent episodes.

### Evidence and verdicts

The native `audit` operation evaluates the compiled admission decision on an
imported context without modifying the engine's admission journal. Conversations
have independent histories. No model, environment tool, embedded code or dataset
reward verifier is executed.

Replay assumes τ²'s serial dispatch order. Tool IDs pair responses where available;
a complete batch without IDs is paired in recorded order. Conflicting IDs and
incomplete ambiguous batches never receive guessed outcomes. Each decision sees
only earlier completed responses, never its own outcome. Facts come from recognized
prior tool outputs and literal customer identity/reason text. There is no hidden
task solution or initial-database substitution. Writes and unknown tools invalidate
potentially stale state, including after errors. Clocks use pinned domain times.
Recorded outputs and the available pre-call facts are retained on historical events.
Observed flight schedules supply itinerary timing; missing schedules or historical
disruption facts remain unavailable rather than being filled from the initial database.
Documented fuvty aliases are mapped only for compatible argument shapes; additional
airline identity lookup tools remain unsupported.

Published traces lack LeanGuard's trusted bound approvals, compensation bindings
and simulator travel events. Missing prerequisites remain missing; neither an
assistant claim nor a generic user “yes” is converted into a confirmation event.
The report assigns one diagnostic category in this priority order:

1. `unsupported_tool`: outside the compiled tool interface.
2. `invalid_arguments`: fails the pinned host schema or unit conversion.
3. `recorded_policy_failure`: a native rule fails beyond identified evidence gaps.
4. `insufficient_evidence`: denial attributable to missing facts, evidence or outcomes.
5. `allow`: both host argument checks and the native decision pass.

All native rule values and errors remain available. Categories do not relax the
policy, and a call can have additional evidence gaps beyond its primary category.
`code_evaluation` is unsupported: arbitrary database code is not equivalent to one
named tool. Denying that interface does not establish that its recorded effect was
wrong. Covering code agents requires interception of their actual effects.

Replay follows the **original recorded continuation**, including outcomes of calls
that would have been blocked. The original dataset reward is preserved; it is not
a new task-success score under enforcement. These audits alone cannot show that
LeanGuard outperforms the source projects' validation methods. Compare matching
policies, tool interfaces and pre-call evidence before labeling an overrefusal;
the [coverage guide](../../docs/coverage.md) records known interpretation differences.

For a consent comparison, independently reconstruct the authorized effects,
resources, payment, charges and conditions from the preceding dialogue, then check
the candidate against that structured receipt. A second model merely approving
the candidate does not establish independent authorization. Use original backend
snapshots only with verified provenance and trajectory mapping; an RL task's
database path cannot automatically identify an SFT conversation's initial state.

### Replay artifacts

| Artifact | Contents |
| --- | --- |
| `calls.jsonl` | Each call's native rules, evidence gaps, import details and original outcome |
| `trajectories.jsonl` | Source row, original reward, first block and per-trajectory accounting |
| `native-audits.jsonl.gz` | Exact native commands and responses |
| `report.json` | Coverage, source/binary fingerprints and download metadata |
| `verification.json` | Independent native rechecks, complete call coverage and artifact hashes |

The download root also contains `downloads.json` with snapshot file hashes.

The [LeanLTL theorems](../../docs/leanltl.md) apply to each supplied native context.
They do not prove the importer, observation authenticity or correspondence with a
source dataset's English policy. Historical run reports remain in Git history;
generated results stay with their run artifacts.
