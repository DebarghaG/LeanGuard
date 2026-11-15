# Human policy authoring and review

Tracked in [roadmap #32](https://github.com/DebarghaG/LeanGuard/issues/32).
This document specifies the workflow; it does not claim the workbench is already
implemented. The UI must help a reviewer answer: what can this agent do, under
what conditions, and what changed?

## A reviewable policy

The default view is a list of rules grouped by affected tool. Each card shows
the rule's effect, action names, condition, time window, history scope, required
facts and units, and the source requirement. Expand a card to inspect the precise
formula, generated Lean, and proof or test evidence. Show unsupported or opaque
parts in place; never silently omit them from a favorable summary.

For example, a document policy should show:

| Card | Human-readable content |
| --- | --- |
| Allowed tools | `read`, `write`; all other actions denied |
| Before writing | A successful read of this resource occurred earlier in this conversation |
| Approval | Matching approval for these exact arguments and backend revision, not revoked or already used |
| Limit on writes | At admission, fewer than 10 principal dispatches in the inclusive preceding 3,600 seconds, and previous amount plus this call's amount at most 10,000 |
| Deployment assumption | Every backend writer participates in the snapshot/dispatch locking contract |

The limit card must explain that reads count toward a later write's quota but
are not themselves constrained by a write-only requirement. The approval card
must not invent expiry unless the pack actually uses an expiring condition.

## Authoring flow

1. Choose tools from authoritative schemas and a small set of policy templates.
2. Edit explicit actions, conditions, scopes, windows, and units in forms.
3. Inspect generated Lean and incomplete/opaque checks as needed.
4. Build with the pinned toolchain and run the axiom audit.
5. Try allowed, denied, and incomplete-evidence scenarios using the compiled
   engine, without executing backend tools.
6. Review the structural changes and changed scenario results against the
   previous compiled pack.
7. Approve a reproducible artifact bundle and publish it through an authorized
   deployment process.

The lifecycle is **draft → compiled → reviewed → published**. Changing an input
to the compiled or reviewed artifact returns it to draft. A compile result is
not a human approval; human approval is not a proof of the English requirement.

One versioned authoring document drives the forms, generated Lean, and preview.
Its first supported constructs should be permit/require/forbid, prerequisite
observations, confirmations, and quotas. Compile these to existing LeanGuard
constructors. Keep the Lean engine as the sole evaluator. Reject unsupported
edits instead of approximating them.

Natural-language assistance can propose a draft and explain choices. It cannot
certify that the policy expresses the user's intention. A reviewer must be able
to inspect and change each proposed rule without using Lean syntax.

## Existing Lean packs and inspection

`RuntimeCore.manifest` currently exports rule IDs, effects, actions, source
strings, schemas, and flattened check names. It loses formula structure, windows,
and scopes. `Check.run` is an arbitrary function; its captured parameters cannot
be reconstructed from `Check.name`, and names need not uniquely identify checks.

Add an additive inspection format derived from the compiled pack. Represent all
`Formula` constructors explicitly. Include built-in parameters only when their
metadata is tied to the actual constructor; custom predicates remain opaque.
Preserve the original pack or refuse edits that would discard opaque behavior.
Never parse Lean pretty-printing to guess semantics.

Every view identifies the engine fingerprint and inspection-format version.
Display four kinds of evidence separately: kernel-checked engine theorems,
pack-specific theorems, executed tests, and deployment assumptions. Show a
custom theorem's exact claim alongside a readable explanation.

## Scenario and change review

Use a chronological timeline with a text/table alternative. A reviewer selects
an event to see native rule results, errors, available facts, and relevant
history. Fixtures are labeled as simulated evidence. Missing evidence remains
visible as insufficient information.

The current audit interface reports rule Boolean values and decisions, not a
complete temporal witness tree. Add engine-derived explanation data as a
separate capability; do not make the browser infer the reason for a temporal
decision. Preserve errors from applicable Boolean branches and intervening
`since` positions, even when a simplified explanation would hide them.

A change review includes additions/removals, widened or narrowed actions,
changed scopes/windows/limits, changed opaque source, and changed native outcomes
on the same scenario corpus. Identical scenario outcomes are sampled evidence,
not equivalence. Only an appropriate Lean proof can establish equivalence.

## Policy publication and individual approvals

These are separate human decisions:

| Decision | Bound artifact | Effect |
| --- | --- | --- |
| Publish a policy | Source, authoring document, dependencies, inspection, audit/test results, and executable digest | Select the reviewed policy for deployment |
| Approve a tool call | Immutable `Proposal.details`, including principal/session, arguments, revision, units, policy fingerprint, and delegated scope | Record a confirmation that the native policy may require |

The tool approval screen shows a readable view plus the exact payload and calls
`confirm` only from an authenticated human authority. Framework interrupts and
model text do not constitute confirmation. Changed state requires a new proposal;
reuse or changed arguments cannot consume the old approval. Rejection and unknown
outcomes must be distinct from successful execution.

Publication verifies the bundle digest and records who reviewed it. Changes to
source, metadata, dependencies, or the binary invalidate approval. The host's
existing journal fingerprint check stays intact. Upgrades and rollbacks need a
fresh compatible journal lifecycle or an explicit audited migration; changing a
binary does not make old history compatible.

## Interface and maintenance requirements

Start with local inspection and deterministic export. Add editing only for
constructs with faithful generation. Keep UI code in the repository, make core
inspection usable without a network, and select a frontend stack based on the
actual editing/accessibility needs. Do not add a hosted application dependency to
the policy engine.

Use keyboard navigation, visible focus, screen-reader labels, clear units,
inline errors, and text equivalents for diagrams. Status must not rely on color.
Escape source/tool strings and default to redacted exports. A future web approval
service must authenticate users, authorize sessions, and protect state-changing
requests; those controls do not belong in agent tools.

Version saved documents and provide deterministic migrations. Preserve unknown
fields only when doing so is lossless; refuse edits that could change unknown
semantics. Keep old format fixtures, deterministic generation tests, native
scenario tests, and accessibility tests in CI. No UI release may silently change
an existing policy's decisions.

Evaluate the interface with non-Lean reviewers on concrete tasks: explain a
denial, fix an incorrect time window, detect a widened permission, and identify
an opaque predicate. Record failures and revise the interface before treating
it as suitable for policy approval.

## Delivery order

| Work | Issue | Depends on |
| --- | --- | --- |
| Workflow design | [#63](https://github.com/DebarghaG/LeanGuard/issues/63) | Existing semantics and host contracts |
| Versioned inspection | [#64](https://github.com/DebarghaG/LeanGuard/issues/64) | Design |
| Structured authoring | [#65](https://github.com/DebarghaG/LeanGuard/issues/65) | Inspection and constructor metadata |
| Accessible workbench | [#66](https://github.com/DebarghaG/LeanGuard/issues/66) | Inspection; authoring for edit mode |
| Scenarios and change review | [#67](https://github.com/DebarghaG/LeanGuard/issues/67) | Inspection and native audit |
| Artifact review/publication | [#68](https://github.com/DebarghaG/LeanGuard/issues/68) | Authoring, scenarios, reproducible builds |
| Tool approval screen | [#69](https://github.com/DebarghaG/LeanGuard/issues/69) | Existing proposals and trusted UI authority |
