# Compiled policy inspection

The native manifest now contains an additive `inspection` document with format
`leanguard.inspection`, version 1. Existing `rules`, `checks`, schemas and
protocol fields remain available. The document preserves every formula node,
including conjunction/disjunction, previous/once/since windows, and history
projections. Windows are inclusive integer seconds; null means unbounded.
It is a display format, not another policy language or an evaluator.

```python
from leanguard.engine import Engine
from leanguard.inspection import inspect_policy

with Engine("example") as engine:
    document = inspect_policy(engine)
```

The Python reader binds the document to the executable fingerprint and includes
the compiled pack's declared property names. Engine theorems, pack claims and
deployment assumptions are listed separately. It rejects missing or unknown
inspection versions. Old executables still work with the normal host; inspection
requires rebuilding with the new native module.

Atoms retain their position and display name, including repeated names. Arbitrary
`Check.run` closures are opaque by default. Names do not identify semantics:
a custom check named `dispatch_quota` is still opaque. Built-in constructors carry
explicit parameters for quotas and action sets; temporal parameters come from
the formula tree itself. Metadata is declared by the compiled source and never
consulted by admission. Custom authors can supply display metadata, so readers
must label it as declared information and treat unknown descriptions as opaque.
Metadata is not a proof that a prose requirement is faithfully implemented.

`Check` has a new optional `inspection` field. Record literals and the `check`
and `eventCheck` helpers remain source compatible. Code using positional
`⟨name, predicate⟩` constructors must migrate to `{ name, run := predicate }` or
provide a third `none` field. Prefer named fields for extensible policy records.
No theorem statement or admission condition changed. Regression proofs establish
that changing an atom's metadata preserves both its value and its errors.

A rebuild changes the binary fingerprint even when decisions are equivalent.
Existing journals remain bound to their old executable; inspection is not a
journal migration mechanism. Keep the old executable and journal together or
start an explicitly separate host lifecycle. Do not bypass fingerprint checks.

Render strings as text, never HTML. Do not silently drop opaque nodes, unknown
operators or schema fields when importing a document into an editor. Preserve
the source pack or refuse unsupported edits. Scenario comparison supplies
sampled evidence; it cannot establish semantic equivalence.
