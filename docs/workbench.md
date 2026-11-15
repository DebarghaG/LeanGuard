# Human policy workbench

The local workbench supports a complete review loop: write a structured policy,
compile and audit it with Lean, inspect the resulting rules, try scenarios, then
accept or reject an exact artifact. It uses native HTML controls and a small
vanilla JavaScript client, packaged with Python; no web service or model is required.

From a development checkout with the pinned Lean toolchain and dependencies:

```sh
python -m pip install -e .
leanguard-workbench --project "$PWD" --workspace /private/my-policy-review
```

Open the private link printed in the terminal. The server binds only to loopback.
The link carries an operator capability, exchanged for an HttpOnly, SameSite
cookie and removed from the address bar. Exact Host/Origin checks, authenticated
mutations, bounded requests and a restrictive content policy protect the local
interface. Keep the link, workspace and local review key outside agent access.
This is a single-operator tool, not an Internet-facing identity service.

1. **Write policy.** Define tools and primitive argument fields. Add permits,
   requirements and forbids with stable rule IDs and requirement source text.
   Forms cover approvals, prior observations, dispatch quotas and unresolved
   operations. Nested schemas and Boolean conditions remain available in the
   structured JSON editor; switching views never translates arbitrary English
   into a claimed proof. Save explicitly. Invalid/unknown versions are rejected.
2. **Inspect compiled rules.** Compile runs the native build and axiom audit in
   an isolated output directory. Review tool coverage and the complete Boolean,
   scope and temporal tree. Quotas show their captured parameters. Coverage
   counts do not imply admission. Custom predicates without structural metadata
   remain explicitly opaque; names never establish their semantics.
3. **Try scenarios.** Edit a normalized request and chronological history, add
   matching approvals or observed reads, and run the native engine. The exact
   JSON editor preserves integers that a browser cannot safely represent. Cases
   report allowed, denied or insufficient evidence, rule truth values and native
   diagnostics. A second compilation compares both binaries against the same
   corpus. These are sampled results, not a complete causal proof.
4. **Review artifact.** Build a bundle after the current scenarios run. Review
   its digest, executable identity, source and assumptions, then accept or reject.
   Download includes an authenticated local review record. Full scenario inputs
   require an explicit opt-in; the default export contains assessments only.
   Follow [artifact review and activation](policy-review.md) for deployment.

Draft changes invalidate compilation and review. Stale windows and external
draft edits cannot silently overwrite the current source. Builds, bundles and
review records remain in the workspace. Restart restores the saved source;
compile and rerun scenarios to begin a fresh review session. There is no hidden
reuse of a previous acceptance or automatic deployment.

Inspect an existing native pack without attempting to reverse arbitrary Lean:

```sh
leanguard-workbench --project "$PWD" --workspace /private/native-review \
  --inspect example --binary .lake/build/bin/leanguard
```

The native view is read-only. Starting a template creates a separate structured
draft; it never rewrites the imported pack. Unsupported authoring constructs are
rejected, not dropped. Pack-specific theorem claims are displayed separately
from engine properties and deployment assumptions.

## Validation and usability

`tests/test_workbench.py` exercises origin/authentication, stale writes, native
scenarios, private exports and exact artifact acceptance. `tests/workbench`
contains a real Chromium flow and axe WCAG A/AA checks, including a mobile layout.
CI pins the browser tooling and reruns this flow. Run `npm ci`,
`npx playwright install chromium` and `npm test` in that directory after building
Lean and installing Python; set `LEANGUARD_TEST_PYTHON` if needed.

Automated accessibility checks do not replace a usability study. Before claiming
non-experts can independently author production policies, observe representative
users creating an approval rule, changing a quota, explaining a denial and
detecting an opaque predicate. Record task completion, mistakes and interpretation
of guarantees in #66; improve the interface from that evidence. The current
interface is local and English-only, with keyboard-accessible native controls.
