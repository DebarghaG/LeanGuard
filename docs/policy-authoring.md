# Structured policy authoring

`leanguard-policy` creates and compiles a small, versioned authoring document.
The generated code calls existing Lean constructors; it does not evaluate policy
in Python or translate natural language into a claimed proof.

```sh
leanguard-policy new > policy.json
leanguard-policy generate policy.json > Policy.lean
leanguard-policy compile policy.json /tmp/my-policy-build --project /path/to/LeanGuard
leanguard-policy inspect documents --binary /tmp/my-policy-build/.lake/build/bin/policy-engine
```

Before reinstalling an editable Python package, the same commands are available
as `python -m leanguard.policy_cli`. Use a reviewed LeanGuard checkout and its
pinned Lean toolchain. Compilation requires Lake, writes a fresh project, builds
the native executable, and runs the transitive axiom audit. It records source,
dependency revisions and source-tree digests, inspection metadata, and executable
identity. It refuses a nonempty output directory or dependency changes during
the build. Build outputs are isolated; dependency source caches may be shared.

Version 1 requires an explicit pack name, adapter unit description, tool schemas,
and rules with stable IDs, action scopes, effects and source clauses. Supported
conditions are always/never, approval with an explicit optional time window,
successful resource observation, never-dispatched actions, quota, single-flight,
and Boolean combinations. Arbitrary Lean predicates and inspection documents are
not editable authoring input. Keep custom packs in Lean and inspect them as
read-only; unsupported edits fail rather than discarding code.

The templates have concrete semantics:

- Approval matches the exact binding and authority, is single-use, and must be
  unrevoked. A null window is unbounded; integer windows are inclusive seconds.
- Observation requires a successful prior action on the same resource in the
  same principal, conversation and workflow. It has no time limit in this template.
- Quotas count all of the principal's dispatches in the window, including failed
  and unresolved operations. They constrain only actions named in that rule.
  The current operation's units count toward the amount limit.
- Single-flight blocks unresolved dispatches in the same conversation or resource.
  An unknown outcome is unresolved until the existing host reconciliation flow
  establishes the result.
- A permit still needs all applicable requirements and no applicable forbids.
  Missing permits and evaluation errors deny by default.

Tool schemas support native object, array, primitive and string-enum types.
Native object schemas allow extra properties; the builder rejects unsupported
`additionalProperties` rather than pretending it enforces them. Every action in
a rule must have a schema, and schema requirements are generated automatically.
Custom facts and unit normalization remain the trusted adapter's responsibility.
The unit description documents that contract; it cannot convert backend data.

Unknown versions/fields, duplicate IDs/JSON keys, invalid action scopes, missing
schema fields, nonfinite numbers and unsafe integers are rejected. Version 1
uses nonnegative integers at most 2^53-1 so the same document can be edited safely
in a browser. More general policies remain available through native Lean.
There is no implicit migration or natural-language generation in this format.

Compilation and axiom auditing check executable code and proof dependencies.
They do not establish that a policy matches its English source, that it allows
useful work, or that an adapter supplies truthful facts. Generated packs report no
invented pack-specific property theorem. Review source, compiled inspection and
native scenario results before accepting an artifact. Changing any source or
dependency requires rebuilding and a fresh review; a different executable cannot
silently reuse an existing host journal.
