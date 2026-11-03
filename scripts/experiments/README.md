# Evaluation tooling

These scripts answer two questions. First, what happens when a small local
model works through τ²-bench tasks with LeanGuard in the loop, compared with the
same model running unguarded? Second, what would LeanGuard have said about
rollouts other people have already published?

Set up the pinned editable τ² checkout and the optional dependencies as described
in the [tooling guide](../README.md), and
build the native engine with `lake build`. Run everything from the repository
root. Dataset and model revisions are pinned in the scripts, and generated
output belongs under the ignored `runs/` directory.

## Local model evaluation

The runner draws tasks from the pinned retail, airline and telecom `base` splits.
The agent and the simulated customer get the normal domain prompts and tools.
Expected actions, scoring assertions and gold databases are used only to score
the finished episode.

### Start the model server

[serve_qwen35.py](serve_qwen35.py) pins the Qwen3.5-4B checkpoint and an ARM64
vLLM Docker image. It needs Docker, GPU access and the model snapshot already in
your Hugging Face cache. Preview the launch command first:

```sh
.venv/bin/python -m scripts.experiments.serve_qwen35 \
  --name leanguard-qwen35-4b --max-num-seqs 16 --prefix-caching --print-command
```

Drop `--print-command` to start the server, and pass `--cache` to point at a
different Hugging Face cache. The launcher serves BF16 weights on GPU 0 with a
32,768-token context and a 20% GPU-memory budget, listening only on loopback port
18000. Those settings were chosen for one machine, so check the hardware and
image assumptions before running elsewhere.

### Run and score episodes

Once the server is up, run paired episodes and score every attempt:

```sh
.venv/bin/python -m scripts.experiments.benchmark \
  --total-tasks 100 --modes baseline generic --concurrency 12 \
  --output runs/qwen35-4b-evaluation
.venv/bin/python -m scripts.experiments.score_saved runs/qwen35-4b-evaluation
```

This samples 100 distinct tasks without replacement (41 retail, 18 airline and
41 telecom) and runs each one twice: once unguarded and once with LeanGuard
returning a generic denial. That makes 200 episodes. `--total-tasks 278` covers
every base task, for 556 episodes.

There is also a `guarded` mode that gives the agent actionable feedback on
denials. It runs by default, so the example above lists `--modes baseline
generic` to leave it out. `--total-tasks` and `--tasks-per-domain` can't be
combined. The output directory must not already exist, and endpoints must be
local. `--help` lists the sampling and resource controls.

### How each episode runs

The policies are fixed for the whole run. Assistant tool calls go through
`GuardHost`, while customer tools keep their own separate role.

Some mutations need the customer's consent. A real deployment would ask through
a trusted confirmation screen; here a separate Qwen call plays that part. It
sees the canonical proposal, the visible dialogue and completed tool outcomes,
but never the hidden customer scenario. It won't approve while a question is
still pending, after the customer has withdrawn, or before a prerequisite is
met. Malformed or missing answers count as a refusal. Only a timeout or an
exhausted output gets one retry; a valid refusal is final, and both attempts
are recorded.

The adapters extract a few facts from the conversation, conservatively. Airline
identity requires an unambiguous literal user ID in a customer message.
Cancellation reasons are matched narrowly against the customer's own text, and
negated or ambiguous reasons count as unknown. Telecom travel evidence comes
from the simulator's live sensor for the authenticated customer's line. When the
evidence isn't there, LeanGuard denies, which can block a task that was in fact
feasible. [Coverage and interpretations](../../docs/coverage.md) lists these
choices.

Every mode shares the same protocol controls. A generation that is empty, mixes
text with a tool call, or makes several tool calls is rejected before anything is
dispatched and retried once in non-thinking mode; a second failure ends the
episode. Reasoning text never becomes a tool call. When the customer simulator
loops on tools or hands off, the intervention is logged, and it never consults
the task solution.

An episode is capped at 240 steps and 1,800 seconds. A request already in flight
has its own 600-second timeout, so it can run past the episode deadline. History
is never quietly truncated to fit the server's context. After three classified
integration errors the scheduler stops starting new episodes, and the episodes
it never started are reported separately.

### What gets saved

The manifest records the task IDs and contents, seeds, source and binary
fingerprints, the benchmark revision and the serving configuration. Each run
keeps its conversations, request logs and per-episode results; guarded runs also
keep native journals, decisions, simulated confirmations and denial checkpoints.
Token usage counts rejected generations and retries, but a transport failure can
leave it incomplete. Seeds don't make output reproducible across different GPU
batching schedules.

### How scores are computed

There are two scores. The deterministic score uses the pinned upstream evaluators
with the natural-language assertions removed. The combined score adds those
assertions back, judged by the same local Qwen model, so it inherits that model's
self-judging bias. Failed attempts stay in the denominator of both, and
unstarted episodes are counted separately.

The upstream scorer works by re-executing the episode's mutations, so it gets a
cleaned copy of the trace. That copy drops only the calls the host never
dispatched, together with their paired responses. Dispatched calls that failed
stay in, because their effects are unknown. The original trace, with every
denial, is kept unchanged. Before a score is accepted, the replay must reproduce
the agent and user database hashes from the live run.

`score_saved` first checks that the run is complete and consistent: report
coverage, task contents, artifacts, and the binary and benchmark fingerprints.
It then rechecks the native journals without dispatching any tool, and uses the
upstream evaluator for task rewards. Episodes that terminated early or failed the
live-state check get a reward of zero in the all-attempts result, with the
upstream diagnostic kept alongside. The JSON and CSV results go to
`all-episode-scores/`, and the script won't overwrite an existing one.

Repeated-denial and recovery metrics only describe what was observed. If the
agent is denied and a later call is admitted, the transcript doesn't show that
the agent understood and fixed the problem. The saved checkpoints don't support
counterfactual branches either.

Live protocol tests call the model and are opt-in:

```sh
.venv/bin/pytest -q -m live tests/experiments/test_rollout.py
```

## External rollout replay

Published τ² rollouts record what an agent actually did. Replaying them through
LeanGuard shows which calls the compiled policy would have admitted, given only
the evidence in the trace. Download the pinned datasets, audit every normalized
conversation, then recheck the saved native decisions independently:

```sh
.venv/bin/python -m scripts.experiments.trajectory_replay \
  runs/external-rollouts --download --output runs/external-rollouts/full
.venv/bin/python -m scripts.experiments.trajectory_verify \
  runs/external-rollouts runs/external-rollouts/full
```

Leave out `--download` to reuse existing snapshots. `--limit` is for debugging;
without it every conversation is processed. The output directory must be new.
[trajectory_data.py](trajectory_data.py) pins these datasets:

- [Snorkel airline](https://huggingface.co/datasets/snorkelai/Tau2-Bench-Airline-With-Code-Agents)
- [Snorkel verified airline](https://huggingface.co/datasets/snorkelai/Tau2-Bench-Verified-Airline-With-Code-Agents)
- [fuvty synthetic](https://huggingface.co/datasets/fuvty/tau-bench-synthetic)
- [AReaL τ²](https://huggingface.co/datasets/inclusionAI/AReaL-tau2-data)

Training datasets often store one conversation as many rows, each a longer
prefix of the last. The importer therefore replays full rollouts and the longest
version of each conversation once, rather than counting every row as an
episode. Prefixes are matched on roles, content, error metadata and tool
arguments, ignoring call IDs that were regenerated between rows; branches that
diverge are kept as separate units. Task definitions carry no execution history,
so they are accounted for separately.

### Evidence available to each decision

Each call is checked with the native `audit` operation, which evaluates the
compiled admission decision against an imported context without writing to the
engine's journal. Every conversation gets its own history. Nothing else runs: no
model, environment tool, embedded code or dataset reward verifier.

Replay assumes τ²'s serial dispatch order. Responses are paired with calls by
tool ID when IDs exist. A complete batch without IDs is paired in recorded
order, but conflicting IDs and incomplete, ambiguous batches are left unpaired
rather than guessed. A decision sees only responses that completed before it,
never its own outcome.

Facts come from two places: the outputs of recognized earlier tool calls, and
literal identity or reason text from the customer. There is no hidden task
solution, and the initial database is never used to fill gaps. Missing flight
schedules or historical disruption facts simply stay unavailable. A write or an
unknown tool invalidates any state it might have changed, even when it returned
an error. Clocks use the pinned domain times, and the recorded outputs and
available pre-call facts are kept on each historical event. The documented fuvty
aliases are mapped only when their argument shapes are compatible; the extra
airline identity lookup tools in that dataset remain unsupported.

Published traces lack three kinds of evidence a live LeanGuard host would
collect: bound user approvals, compensation bindings and simulator travel
events. Replay leaves these missing. An assistant saying the customer agreed, or
a customer's generic "yes", does not become a confirmation event.

### Verdict categories

Each call gets one diagnostic category, assigned by the first match in this
order:

1. `unsupported_tool`: the tool isn't in the compiled tool interface.
2. `invalid_arguments`: the call fails the pinned host schema or unit conversion.
3. `recorded_policy_failure`: a native rule fails for a reason beyond the
   identified evidence gaps.
4. `insufficient_evidence`: the denial is explained by missing facts, evidence
   or outcomes.
5. `allow`: the host's argument checks and the native decision both pass.

The category is a summary for reading reports. It doesn't relax the policy, and
every native rule value and error remains in the output, including evidence gaps
beyond the primary category.

The `code_evaluation` tool, which runs arbitrary code against the database, is
unsupported because it doesn't correspond to any one named tool. A denial there
says only that LeanGuard can't see the effect; covering code agents would mean
intercepting the effects of the code itself.

### Replay artifacts

| Artifact | Contents |
| --- | --- |
| `calls.jsonl` | Each call's native rules, evidence gaps, import details and original outcome |
| `trajectories.jsonl` | Source row, original reward, first block and per-trajectory accounting |
| `native-audits.jsonl.gz` | Exact native commands and responses |
| `report.json` | Coverage, source and binary fingerprints, and download metadata |
| `verification.json` | Independent native rechecks, complete call coverage and artifact hashes |

The download root also holds `downloads.json`, with a hash of every snapshot
file.

## Interpreting the results

Neither experiment produces an official benchmark score. The local runs are
instrumented self-play on current text-domain tasks, and their timings aren't a
controlled measurement of serving throughput. Neither score proves full
compliance with the English policy.

The simulated confirmation screen is itself a model, and a model can approve
the wrong thing. Approval evidence in these runs is only as good as that model's
judgment; it tells you nothing about whether the acting agent understood the
customer. Production integrations need confirmation from an independently
authorized, structured source, as discussed in the
[guarantee boundary](../../docs/guarantees.md).

Replay follows the original recorded continuation, including outcomes of calls
LeanGuard would have blocked, so later verdicts describe the history as it
actually happened. The dataset's original reward is carried through unchanged
and says nothing about task success under enforcement. For the same reason,
these audits alone can't show that LeanGuard beats the source projects'
validation methods. Before calling a denial an over-refusal, check that the
policies, tool interfaces and pre-call evidence actually match; the
[coverage guide](../../docs/coverage.md) records the known differences in
interpretation.

To compare consent handling properly, reconstruct what the customer authorized
from the preceding dialogue, as a structured receipt of effects, resources,
payment, charges and conditions, and check the candidate call against it.
Asking a second model whether it approves the call is no substitute. Original
backend snapshots are usable only with verified provenance and a mapping from
trajectory to snapshot; an RL task's database path can't identify the initial
state of an SFT conversation by itself.

The [LeanLTL theorems](../../docs/leanltl.md) hold for each native context that
replay constructs. They don't cover the importer, whether the recorded
observations are authentic, or whether a context matches the source dataset's
English policy. Historical run reports remain in Git history, and generated
results stay with their run artifacts.
