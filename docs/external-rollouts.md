# Published trajectory replay

LeanGuard can audit published retail, airline, and telecom conversations without
generating new conversations. It invokes the compiled Lean policy pack before
each recorded assistant tool dispatch and exports the native allow/block decision,
every applicable rule value, and the original recorded outcome. No environment
tool, embedded Python expression, or dataset reward verifier is executed.

## Reproduce

Install the pinned editable τ² checkout as described in the
[tooling guide](../scripts/README.md), build the
native engine, and install the optional data readers:

```sh
.venv/bin/pip install -e '.[experiments]'
.venv/bin/python -m scripts.experiments.trajectory_replay \
  runs/external-rollouts --download --output runs/external-rollouts/full
.venv/bin/python -m scripts.experiments.trajectory_verify \
  runs/external-rollouts runs/external-rollouts/full
```

Omit `--download` when snapshots are already present. The default processes every
conversation; `--limit` is only for debugging. Output directories must be new so
existing results cannot be silently overwritten. The four dataset revisions are
pinned in `scripts/experiments/trajectory_data.py`; `downloads.json` records file
hashes. Dataset files, conversation text, and native audit journals stay under the
ignored `runs/` directory.

## What is replayed

| Dataset | Replay units | Additional rows accounted for |
| --- | ---: | --- |
| [Snorkel airline](https://huggingface.co/datasets/snorkelai/Tau2-Bench-Airline-With-Code-Agents) | 500 full rollouts | — |
| [Snorkel verified airline](https://huggingface.co/datasets/snorkelai/Tau2-Bench-Verified-Airline-With-Code-Agents) | 996 full rollouts | — |
| [fuvty synthetic](https://huggingface.co/datasets/fuvty/tau-bench-synthetic) | 1,464 full rollouts | 4,270 matching training prefixes; 280 task definitions |
| [AReaL τ²](https://huggingface.co/datasets/inclusionAI/AReaL-tau2-data) | 2,499 maximal conversation prefixes | 33,531 training rows represented; 1,982 task definitions |

Training prefixes are compared by message content, role, error metadata, and tool
arguments. Regenerated tool-call IDs do not create a new conversation. Divergent
branches are retained; none occur in these pinned snapshots. Task definitions do
not contain an execution history and cannot be replayed. All 37,801 training-prefix
rows are accounted for, rather than being counted as independent episodes.

## Meaning of a verdict

The native `audit` operation evaluates the same compiled policy decision used by
admission. It accepts an explicit imported context and does not mutate the engine's
runtime admission journal. A single engine is reused per domain with an independent
history for each conversation.

Replay follows τ²'s serial dispatch loop. Within an assistant tool batch, call IDs
match responses when available. For formats that omit response IDs, a complete
batch is paired in recorded order. Conflicting IDs and incomplete ambiguous batches
never receive guessed outcomes. Each call sees only earlier completed responses;
its own response becomes available after its decision. Positional pairing and
serial dispatch are explicit import assumptions, not timestamp-derived facts.

Domain facts come from preceding recognized tool outputs. Literal customer text
supplies identity and the existing narrow cancellation-reason extraction. There is
no hidden task solution, initial-database substitution, or future tool result in a
decision. Missing objects and incomplete collections remain missing. Writes and
unknown tools invalidate potentially stale state, including after an error.
Simulation clocks use the pinned τ² domain times; wall-clock trace timestamps are
not substituted for simulation time.

The public datasets do not record LeanGuard's trusted, action-bound confirmation
events, compensation bindings, or simulator travel sensor events. The strict native
decision still denies when those prerequisites are absent. The report separates
those evidence gaps from other false policy conditions. It never fabricates a
confirmation from an assistant claim or a generic user “yes.”

`category` is mutually exclusive, in this order:

1. `unsupported_tool`: the interface is outside the compiled tool surface.
2. `invalid_arguments`: arguments fail the pinned host schema or unit conversion.
3. `recorded_policy_failure`: at least one native rule fails beyond the identified
   unavailable evidence. Other evidence gaps may also occur on the same call.
4. `insufficient_evidence`: native denial is attributable to missing recorded
   evidence, facts, or unresolved outcomes.
5. `allow`: the host argument gate and native decision both pass.

The complete native decision, including errors and failed rules, is retained even
when a diagnostic category describes an evidence gap. Diagnostic classification
does not relax the executable policy.

Unsupported code agents are a material coverage limit. `code_evaluation` can directly
read and write database objects; it is not equivalent to any one named tool.
LeanGuard defaults to denial and this importer never executes or interprets that
code as trusted domain facts. fuvty's documented retail lookup/cancellation aliases
and airline reservation/cancellation aliases are mapped only for compatible
argument shapes. Additional airline identity lookup tools remain unsupported.

After each verdict, replay follows the **original recorded continuation**, including
outcomes of calls LeanGuard would have denied. Thus subsequent verdicts are
conditional checks on a fixed historical trace. The stored reward is the dataset's
original reward, not a new success score after enforcement. In particular, a
published-success rollout containing a denial is not automatically a false positive:
datasets can use different policies, successful tools can violate prose policy, and
the recorded trace can lack facts available to a live host.

## Comparison with the source evaluations

The source projects were not trying to emit LeanGuard's internal evidence format.
Snorkel compares bespoke tools with direct Python database access and evaluates
final database differences against expected outcomes. Its verified release uses
corrected tasks and an adapted code-agent policy; it intentionally samples both
successful and failed rollouts. Refusing its code interface does not establish
that a particular operation was wrong.

fuvty constructs expected actions from database entities and generates GLM-5
trajectories against those tasks. Its documented templates include an address
change followed by an item change. The current cross-action `retail.modify_once`
interpretation conflicts with that intended workflow. AReaL publishes synthetic
SFT conversations and RL tasks with database-specific verification. Its
[generation paper](https://arxiv.org/html/2601.22607v1) also describes trajectory
checks for tool correctness, grounding, dialogue coherence and domain-policy
compliance, followed by repairs. It studies errors introduced by the simulated
customer. Describing that workflow as only final-state scoring understates its
validation. Its RL database paths must not be assumed to identify an SFT
conversation's initial state without a verified join. These are differences in
evaluation contracts, not evidence of careless dataset construction.

LeanGuard's intended additional guarantee is formal enforcement before an effect
executes. The present playback cannot establish superiority over those methods:
it has less environment evidence, lacks original LeanGuard approval events, and
does not support the code interpreter. For example, sample 27 contains explicit
approval of the exact shipping-address update; its missing bound approval event
is an integration gap, not evidence that the actor misunderstood consent. Sample
19 performs an explicitly approved booking through direct database writes; the
unsupported interface alone says nothing about whether those writes are correct.

For a consent comparison, reconstruct the authorized proposal from the preceding
dialogue independently of the next recorded call. A validated structured receipt
must identify the permitted effects, resources, payment, charges and conditions.
Check the recorded action against that receipt and its temporal history. A second
model simply approving the candidate is not an independent authorization guarantee.
Use original backend snapshots only when their provenance and trajectory mapping
are established; otherwise absent pre-call facts remain not assessable. Published
task rewards and LeanGuard's native denials cannot by themselves establish which
system better follows the same policy.

See the source dataset cards linked above and the
[random 50-call qualitative review](random-50-playback-review.md). The
[over-refusal validation report](overrefusal-fixes.md) records the adapter fixes
and complete native replay rerun.

## Artifacts and guarantees

- `calls.jsonl`: one result per assistant call, including native rules, evidence
  gaps, alias mapping, pairing method, and original tool outcome.
- `trajectories.jsonl`: one result per replay unit, with its source row, original
  reward, first block, counts, and import diagnostics.
- `native-audits.jsonl.gz`: every exact native command and response.
- `report.json`: domain/dataset totals, source and binary hashes, downloads, and
  coverage accounting.
- `verification.json`: complete assistant-call coverage checks, independently
  rerun native responses, artifact hashes, and rule evaluation counts.

The [LeanLTL correspondence theorems](leanltl.md) apply to the native decision on
each supplied context. They do not prove the importer, the authenticity of a
downloaded observation, or equivalence between a dataset's English instructions and
LeanGuard's selected policy. This run adds broad executable regression evidence;
it does not extend the [formal guarantee boundary](guarantees.md).

See [the completed September 2026 results](external-rollouts-results.md).
