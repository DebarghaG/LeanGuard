# LeanGuard

LeanGuard combines Lean policy evaluation and proofs with a durable Python
enforcement host. Keep the distinction between proved properties, runtime
checks, and deployment assumptions explicit.

## Repository map

- `LeanGuard/`: policy definitions, evaluation, runtime, domain policies,
  proofs, and Lean regression tests.
- `python/leanguard/`: engine client, host, adapters, CLI, and integrations.
- `tests/`: Python regressions and native integration tests.
- `scripts/experiments/`: benchmark execution, import, replay, and scoring.
- `tests/experiments/`: tests for experiment tooling.
- `examples/`: custom policies, repair examples, and Dogwood comparisons.
- `docs/`: semantics, guarantees, coverage, and tutorials.
- `scripts/verify.py`: local verification gate.
- `.github/workflows/`: CI and release verification.

Production code must not depend on experiment scripts, model clients, or
dataset loaders.

## Working approach

- Read the implementation, its callers, and existing tests before editing.
- Make the smallest coherent change that solves the actual problem.
- Prefer existing types and operations over intermediate representations,
  new helpers, or generalized frameworks.
- Treat line reduction as a benefit, not a correctness criterion.
- Preserve observable behavior during refactors: decisions, diagnostics,
  event ordering, normalization, identity selection, and replay behavior.
- Explain intentional behavior changes and update the affected contracts.
- Keep unrelated findings separate from the current patch.

## Soundness boundaries

- Never make a proof pass by weakening its statement, changing the
  specification to mirror the implementation, or removing difficult cases.
- Do not introduce `sorry`, custom axioms, or `native_decide` into audited
  code. The audit permits only `propext`, `Classical.choice`, and `Quot.sound`.
- For semantic refactors, prefer an equivalence proof covering the complete
  result. Equal allow/deny decisions alone do not establish equal behavior.
- Do not treat agent text, imported traces, or tool output as authoritative
  identity, approval, or backend facts without the required validation.
- Preserve approval binding, dispatch reservations, and journal recovery.
  An exception after dispatch does not establish that the tool did nothing.
- Keep Lean guarantees separate from Python enforcement and assumptions
  about adapters, approval authorities, and deployment.
- Do not describe heuristic language extraction as semantic verification.

## Verification

Use the pinned toolchain and dependencies. Setup instructions live in
`scripts/README.md`; do not upgrade dependencies incidentally.

During development, run checks appropriate to the changed component:

```sh
lake build <affected-target>
.venv/bin/python -m pytest -q <affected-tests>
```

Before presenting a code change as ready for review, run the local gate:

```sh
.venv/bin/python scripts/verify.py
```

- Fix the underlying failure; do not delete assertions or weaken expected
  results merely to make tests pass.
- Extend existing regressions when practical. Test externally meaningful
  behavior, including denial, malformed input, and uncertain outcomes.
- Install the relevant optional dependencies when testing an integration.
  Report skips and missing coverage.
- Run live/model tests only when the task authorizes those runs.
- For documentation-only changes, check claims against implementation and
  validate affected commands or links as appropriate.
- In worktrees, verify that Python imports and the native executable come
  from the intended checkout. Do not share `.lake/build`.
- If worktrees share `.lake/packages`, avoid an unscoped `lake clean`.
- Distinguish local validation from remote CI. A pending run is not a pass.

## Read when relevant

| Work | References |
| --- | --- |
| Policy semantics or proofs | `docs/native-dsl.md`, `docs/leanltl.md`, corresponding proof files |
| Host, adapters, approval, or recovery | `docs/guarantees.md`, corresponding host and integration tests |
| Domain policies | `docs/coverage.md`, corresponding domain tests |
| Delegation or A2A transports | `docs/multi-agent.md`, corresponding transport tests |
| Experiments and replay | `scripts/experiments/README.md` |
| Dogwood examples | `examples/dogwood/README.md`, `.github/workflows/verify.yml` |
| Packaging or releases | `scripts/README.md`, `.github/workflows/release.yml` |

Load the relevant references; do not read every guide for every task.

Regenerate A2A bindings through `scripts/gen_a2a_grpc.py`. Do not hand-edit
generated bindings. Keep generator and runtime requirements compatible.

## DJ review

When asked to conduct a DJ review, ask:

- What requirement does this code satisfy?
- What observable behavior would change if it disappeared?
- Can an existing operation express the same thing more directly?
- Is the apparent duplication serving different trust boundaries?
- What evidence would establish that the simpler version is equivalent?

File actionable findings with locations, evidence, and a proposed direction.
Do not manufacture findings or classify hypothetical future changes as
current bugs.

Use fresh-context reviewers to challenge substantial findings and patches.
Give them the relevant code and intended contract; let them reach their own
conclusions. Validate automated review comments against the implementation.

## Branches and contribution writing

- Use focused topic branches and reviewable PRs.
- Preserve unrelated user changes.
- Never merge or enable auto-merge without explicit user permission.
- Describe the problem, resulting behavior, validation, and material limits.
- Write for a reviewer who has not seen the conversation.
- Explain non-obvious constraints in comments; omit edit history and
  narration of obvious code.
- Report what passed, what remains unresolved, and what was not checked.
