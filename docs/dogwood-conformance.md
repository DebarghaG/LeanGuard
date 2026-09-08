# Dogwood introduction conformance

Source: the user-supplied [Introducing Dogwood: runtime verification for AI agents](https://aws.amazon.com/blogs/opensource/introducing-dogwood-runtime-verification-for-ai-agents/)
article, published August 6, 2026. Policies are translated into ordinary Lean declarations
in `LeanGuard/DogwoodExamples.lean`; fixtures and expected verdicts are data in
`scripts/conformance.py`. Python does not evaluate any policy.

Run from the project directory:

```sh
lake build
.venv/bin/python -m scripts.conformance
.venv/bin/pytest -q tests/test_dogwood.py
```

The first command builds both the live engine and the standalone, read-only
`leanguard-conformance` executable. The second prints machine-readable expected and
actual decisions and fails on a mismatch or predicate evaluation error. The third also
exercises the live admission protocol, durable host, and MCP integration.

## Original trace fragments

`A` means allow and `D` means deny; only request verdicts are listed.

| Article example | Expected and observed |
|---|---|
| Exact stock/amount approval within one hour | D, A, D |
| Small sale and temporal approval | D, A, D |
| At most five requests in an hour | A, A, A, A, A, D |
| At most three distinct recipients, including denied attempts | A, A, A, D, D |
| Sum requests, including in-flight calls | A, A, D, D |
| Deliberately unsafe response-only sum | A, A, A, A |
| Compare candidate with settled total (`bind`) | A, D, A |

All 28 original request verdicts match. The running-sum section has no separate trace;
the safe column of the concurrency example exercises that policy, and an added fixture
tests totals of 2000, 4000, 5000, and 5001. The introductory confidentiality restriction
also has an added concrete trace: contact is allowed before the confidential read,
denied afterwards, and unaffected for a different principal.

There are 21 deterministic trace cases and 73 request verdicts including these additions:
inclusive expiry, one-second expiry failure, reusable approvals, exact field matching,
false approval outputs, repeated recipients, distinct-set expiry, retained denials,
equal-timestamp multiplicity, principal isolation and cross-session principal scope,
empty settled history, public versus confidential reads, and exact very large integers.

Additional tests check missing output fields, clock rollback, altered outcome inputs,
request/output spoofing, rejection of the unsafe pack by the live engine, actual output
retention across host replay, and the MCP approval flow. The live engine test admits
two transfers without any outcomes, denies the third, records the first two outcomes,
and still denies the next transfer. This checks admission accounting independently of
the Python host's conservative serialization.

## Deliberate interpretation choices

- The article's forbid-only snippets assume an underlying permit. A policy set made
  only of forbids defaults to deny even below the limit. The test packs supply a base
  permit so the complete policies produce the article's advertised verdicts.
- The approval examples permit the `ApproveSale` tool itself in live tests. Their sale
  condition requires its real successful response to contain `approved = true` and
  matching historical input fields. Merely requesting approval or supplying a claimed
  output on the request cannot authorize a sale. The backend must consult a genuine
  approval authority; an agent-controlled echo tool would break that assumption.
- Article approvals are reusable for one hour, with principal-based correlation.
  They are not silently replaced by the stronger-but-different single-use, conversation-
  bound `confirmed` helper. `confirmedWithin` separately provides expiring one-use
  approvals for policies that want that behavior.
- Requests denied by the native policy stay in request-based windows. Thus the denied
  fourth recipient continues to affect the later repeated-recipient request. Existing
  dispatch quotas remain separate and do not count denied attempts.
- Whole-number monetary values use the article's dollar units in these fixtures.
  Benchmark adapters continue to use integer cents. No floating-point arithmetic or
  machine-integer wraparound is introduced into the Lean aggregate.
- Replay maps article `response` to the live protocol's `success` event kind and does
  not invent missing requests or dispatches. It accepts trusted partial histories and
  cannot execute tools. Live outcome correlation is tested separately and stays strict.

## Scope of the result

These are reproducible tests against the article's published expected verdicts, **not**
a cross-engine differential run against the Dogwood interpreter or a proof of complete
MFOTL/Cedar compatibility. Native temporal semantics, query-window selection, bounded
confirmation properties, and deduplication laws have Lean proofs. General first-order
joins, optimized streaming, a distributed execution scheduler, and verification of
the external host are not established by this suite. No OPA or Dogwood dependency is
needed for any example tested here.
