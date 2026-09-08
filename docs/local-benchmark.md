# Local Qwen3.5-4B evaluation

This experiment uses real retail, airline, and telecom tasks from the pinned
`base` splits of `sierra-research/tau2-bench` at
`672227c6b6676edc20d57ea53b7000262aae77b9`. That revision includes newer task fixes;
it is not an untouched historical τ² leaderboard release.

The agent receives the normal domain policy and tools. The simulated customer
receives its normal scenario and, in telecom, its independent user tools.
Neither the agent nor the guardrail adapter receives expected actions, scoring
assertions, or a gold database. Those are used only after execution for scoring.

## Serving

The base [Qwen/Qwen3.5-4B checkpoint](https://huggingface.co/Qwen/Qwen3.5-4B)
is served locally with vLLM in BF16, without LoRA, SFT, DPO, or quantization.
The cached snapshot is `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`.
The launcher pins the official vLLM 0.22.0 ARM64 image by digest
`sha256:6fca82f415f2a3270aec7d70b84e0d1b5b0d0e6260c7fd15eb4478d48db06485`.
The launcher is `scripts/serve_qwen35.py`; it mounts the cache read-only, uses
GPU 0, and publishes only a loopback port. It never stops existing services.

The server uses a 32,768-token context, at most 16 active sequences, and a
20% GPU-memory budget. These are bounded local operating settings, not the
model's advertised maximum context. Eager execution avoids a long graph-build
step on this GB10 machine. The model card specifies the `qwen3` reasoning parser
and `qwen3_coder` tool parser.

The initially installed vLLM 0.19.0 was smoke-tested and exposed a known Qwen3.5
reasoning/tool-boundary issue: some complete tool calls were left in the reasoning
field, yielding an empty assistant message. This is distinct from a task failure.
The [newer upstream parser](https://docs.vllm.ai/en/v0.22.0/api/vllm/reasoning/qwen3_reasoning_parser/)
explicitly handles that boundary. Initial smoke artifacts are retained separately.
The initial `leanguard-qwen35-4b` container is stopped; the upgraded container is
named `leanguard-qwen35-4b-v022`. The parallel experiment uses
`leanguard-qwen35-4b-parallel` at `http://127.0.0.1:18000/v1`; both older
containers are retained, stopped. The new server enables prefix caching, which
vLLM labels experimental for this hybrid model. Its short repeated-prefix probe
is not representative of every long tool conversation.

The first upgraded-server batch also exposed a local adapter issue: date-valued
telecom results were not JSON serializable, and re-serializing already-converted
model results changed numeric wire types. That batch was stopped and preserved
as an integration diagnostic. The adapter now uses the benchmark's own wire
representation once. Regression tests compare guarded versus direct outputs and
verify that date-valued results durably complete their native reservations.

## Experiment

First follow the README's pinned `.tau2` checkout and editable-install instructions.
The runner checks that checkout's revision; benchmark data is not committed here.

```sh
.venv/bin/python scripts/serve_qwen35.py \
  --name leanguard-qwen35-4b-parallel --max-num-seqs 16 --prefix-caching --print-command
.venv/bin/python -m leanguard.benchmark \
  --total-tasks 100 --modes baseline generic --concurrency 12 \
  --output runs/qwen35-4b-leanltl-generic-200-20260907
```

This command runs 200 episodes: 100 distinct tasks, each with an unguarded baseline
and LeanGuard returning only generic denial text. It allocates tasks proportionally
across the complete base splits: 41 retail, 18 airline, and 41 telecom. Selection is
seeded and without replacement. No actionable-feedback arm runs in this experiment.
`--total-tasks` and `--tasks-per-domain` are mutually exclusive. To select all 278
base tasks, use `--total-tasks 278`; with these two modes that gives 556 episodes.

The endpoint can be supplied with `--endpoint`; non-local endpoints are rejected.
The default is one trial on a fixed, seeded random sample of ten tasks per domain,
in three modes: baseline, generic denial, and actionable denial feedback (named
`guarded`). This gives 90 episodes total. Both guarded modes use identical native
policies and confirmation machinery; only the denial text differs. The runner refuses to
overwrite an existing experiment directory. `--no-thinking` provides a separate
non-thinking experiment rather than silently changing the model configuration.

The agent uses thinking mode, temperature 1.0, top-p 0.95, top-k 20, presence penalty
1.5, and an 8,192-token output cap. The customer uses non-thinking mode, temperature
0.7, top-p 0.8, top-k 20, presence penalty 1.5, and a 2,048-token cap. These follow
the model card's general sampling profiles. Both use the same local model.
Tasks are capped at 240 orchestration steps, ten tool errors, and 1,800 seconds
per episode. A pending inference request is additionally bounded by its own
600-second timeout, so wall time can exceed the episode cap before control returns.
Long conversations remain bounded by the server context; history is not silently
truncated. The previous 30-episode pilot and its smaller limits are preserved.

All three arms apply the same protocol controls. An empty, mixed text/tool, or
multi-tool assistant generation is rejected before dispatch and retried once in
non-thinking mode. Exhaustion remains a failed episode. Reasoning text is never
converted into tool calls. The customer yields actual device observations after
four consecutive tool calls and terminates a completed human-tool handoff. These
deterministic simulator interventions are logged; they do not consult scoring
assertions. This changes the experimental protocol, so comparisons with the older
pilot are descriptive, not an isolated estimate of feedback's effect.

Retry instructions are merged into the one leading system message required
by Qwen's template. An earlier batch was stopped after this boundary failed;
its logs remain an integration diagnostic, not part of the corrected experiment.
The opt-in live regression injects three invalid response shapes after both user
and tool messages and sends the retry through the real local server, including its
chat-template validation, without dispatching tools. These are preflight tests,
not model-quality samples:

```sh
LEANGUARD_LIVE_TESTS=1 .venv/bin/pytest -q tests/test_rollout.py -k live_qwen_retry
```

`batch.py` owns bounded scheduling and cooperative stopping; `rollout.py` owns
interaction controls; `benchmark.py` wires these into tasks, scoring, and artifacts.
Only as many jobs as there are workers are submitted at once. The runner halts
after three classified provider/harness errors by default
(`--max-integration-errors`). Pending episodes are cancelled and active workers
stop at their next generation or tool-dispatch boundary; an in-flight inference
may still run until its request timeout. Model protocol exhaustion and native
policy denials are not circuit-breaker failures. Halted runs report unstarted
episodes separately rather than presenting them as evaluated episodes. New run
directories use descriptive experiment names and dates; source fingerprints and
the manifest describe the implementation and settings.

The manifest records task IDs, seeds, task-content digest, server version and
model path, package versions, GPU/driver, compiled-policy fingerprint, and runner
fingerprint. Conversations, LLM request logs, per-episode results, and a summary
are retained. Guarded runs additionally retain SQLite journals, native decisions,
events, simulated confirmations, and checkpoints at each distinct denied
action/argument pair. Returned-generation usage includes rejected attempts and
retries, including on failed episodes. Confirmation and judge usage are recorded
separately. Transport or response-parsing failures may have consumed tokens without
returning usable accounting. Seeds do not guarantee bitwise identical
generation under different GPU batching schedules.

After the report is complete, score every attempted episode and verify each saved
native journal against the exact compiled LeanGuard binary used in the run:

```sh
.venv/bin/python -m leanguard.score_saved \
  runs/qwen35-4b-leanltl-generic-200-20260907
```

This produces immutable JSON and CSV sidecars in `all-episode-scores/`. The scorer
checks task contents, report coverage, per-episode artifacts, and the binary and
benchmark fingerprints. It replays native commands without dispatching domain
tools. Completed task rewards are checked again with the pinned upstream evaluator;
premature terminations receive its zero reward. A failed live-state scoring check
receives a conservative zero in the all-attempts result, with any upstream replay
reward retained separately. Unstarted episodes remain explicitly unstarted.
Deterministic rewards exclude natural-language assertions as in the live runner;
the original local-model combined scores are retained separately. Neither measure
is a proof of complete English-policy compliance.

## Guarded-mode interpretation

The native Lean packs are fixed, not generated or amended by the tested model.
All assistant tool calls pass through the existing durable `GuardHost`.
User tools retain their distinct role and synchronize through the existing adapter.

A separate customer-model call simulates the trusted confirmation UI for proposed
mutations. It sees the canonical proposal, visible customer/assistant dialogue,
and completed host tool outcomes. It also sees the proposed item replacements,
payment method and item price difference resolved from the snapshot. The hidden
scenario is not supplied to this check: later explicit customer choices determine
consent. Multiple approved orders can require separate calls; a pending question,
withdrawal or unmet prerequisite does not authorize execution.

The confirmation call uses Qwen's reasoning mode with an 8,192-token output cap
and a 360-second timeout per attempt. A timeout or exhausted output budget gets
one retry with a presence penalty of 1.5 to reduce repetitive generation. A valid
denial is final; malformed verdicts also fail closed without a retry. Both attempts
are recorded. The real-model regression checks cover this recovery path. This
increases confirmation latency compared with the original 512-token check. It must
return a Boolean approval; malformed, truncated or unavailable approval denies.
This is **an instrumented experiment**, not the stock conversational confirmation mechanism;
the customer simulator is an unverified stand-in for a real human/UI authority.
The service agent cannot directly manufacture these approval events, but a mistake
by the separate confirmation model can still mint incorrect consent evidence.
Passing model regression tests does not establish semantic consent soundness;
see the [guarantee boundary](guarantees.md) and
[over-refusal validation report](overrefusal-fixes.md).

Airline identity is observed only when the simulated customer's actual message
literally contains an unambiguous database user ID. It is not taken from hidden
task metadata or inferred from an agent's tool arguments. Cancellation reasons
use narrow, documented matching of customer-originated messages. More complex
language-to-evidence interpretation is not established by this runner. Missing
compensation evidence can therefore block an otherwise feasible task; such adapter
limitations must not be attributed solely to the tested model. For telecom roaming,
the benchmark supplies trusted evidence from the live simulator's `is_abroad`
sensor, restricted to the authenticated customer's line matching the device phone
number. It does not read hidden task assertions or accept agent-authored claims.
Travel-state changes require a fresh session; this is not a production sensor adapter.

Cancellation negation is scoped to the clause mentioning the reason. For example,
an unrelated "not Basic Economy" sentence must not erase an explicit health
statement. Negated reasons and multiple reason categories still fail closed. This
literal recognizer is not a general solution to paraphrases, hypotheticals, or intent.

An unresolved read-only identity lookup is allowed to return an ordinary tool error;
it neither authenticates the customer nor permits a switch to another resolved
account. The adapter records a terminal failure only when a tool marked read-only
raises without changing either simulator database. Uncertain mutation outcomes
still fail closed. This relies on the simulator's read-only metadata and state hashes,
not a proof about arbitrary external side effects.

## Scoring and limits

- Deterministic scores use the upstream database, environment-assertion, action,
  and communication evaluators, gated by the task's original reward basis.
  Retail's natural-language assertions are excluded from this **partial** score.
- Retail assertions are separately judged by the local Qwen model. A combined
  local score includes those judgments, but is subject to self-judge bias and
  is not an independent measure of policy compliance. Missing or malformed judge
  output is recorded as an unavailable combined score, not a pass.
- The upstream evaluator replays mutating calls. For guarded trajectories, the
  scoring copy omits only calls that the guard host did not dispatch and their
  paired responses. The complete original trajectory and denials are retained.
  A strict replay must reproduce both the live agent and user database hashes
  before a score is accepted. Dispatched calls that failed are not silently removed.
- Endpoint failures, malformed model responses, and other episode exceptions stay
  in the attempted-task denominator. Native denials and adapter errors are reported
  separately. A denial count alone does not establish that every denial was correct.
- Recovery metrics group repeated identical blocked calls and measure subsequent
  admission of that same call, including assistant-turn recovery at 1, 3, and 5 turns.
  Changed-argument repairs are not automatically recognized. These are observational
  indicators, not verified semantic repair rates. Independent review must label
  genuine violations, false interventions, benign errors, and correct alternative
  actions. Checkpoints preserve evidence for that review; counterfactual branching
  is not implemented by merely saving them.
- Final-state environment assertions are retained even after premature termination,
  explicitly as diagnostics. They do not replace the original reward. Known task-data
  conflicts are flagged in the manifest; no tasks or reference answers are rewritten.
- This small, single-trial, local self-play sample is not an official leaderboard
  score or a statistically conclusive causal comparison. No external model API or
  paid judge is used. The GPU is shared with pre-existing services, so timings are
  not controlled, exclusive-hardware performance measurements.

## Autoformalization

Autoformalization is not implemented by this benchmark runner. The experiment uses
the already-written Lean policies. A future offline pipeline would preserve source
passages, generate typed native Lean candidates, compile/prove/test them, report
ambiguous or omitted requirements, and require source-to-policy review before
promotion. Lean checks the formal statements, not the fidelity of an LLM's English
translation. The tested agent must not generate or relax its own enforcement pack.
