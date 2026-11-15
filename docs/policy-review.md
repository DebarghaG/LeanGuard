# Native scenarios and artifact review

Policy review and individual tool-call approval are separate decisions. This
workflow reviews a compiled pack; it does not create `GuardHost` confirmations
or authorize a particular operation.

## Scenarios

Use a `leanguard.scenarios` version 1 document containing `cases`. Each case has
an `id`, a normalized `request` event, chronological `history`, an explicit
`history_complete` Boolean, and a `missing_evidence` string list. Event fields
follow [the replay API](../python/leanguard/replay.py); facts and histories here are fixtures, not production
authority. The workbench includes editable examples.

```sh
leanguard-policy scenarios documents /tmp/my-policy-build/.lake/build/bin/policy-engine scenarios.json
leanguard-policy compare example .lake/build/bin/leanguard \
  documents /tmp/my-policy-build/.lake/build/bin/policy-engine scenarios.json
```

Results come from the native `audit` operation. No backend adapter is instantiated
and no dispatch is recorded. Missing evidence or native predicate errors produce
`insufficient_evidence`. Comparisons use the exact same corpus and report changed
assessments plus structural changes keyed by stable rule IDs. Scenario agreement
is sampled evidence, not equivalence or proof of an English requirement.

Rule truth values, error/reason labels and the supplied event timeline help a
reviewer investigate a denial. The current native evidence list is not a complete
causal witness trace. Temporal evaluation still preserves eager errors and all
intervening `since` positions. Delegated histories are explicitly rejected here;
this read-only API does not replay the multi-agent authority state machine.

## Review bundles

```sh
leanguard-policy bundle /tmp/my-policy-build /tmp/review-bundle scenarios.json
leanguard-policy review-key /private/operator-review.key
# Run this only after a human inspects the exact bundle:
leanguard-policy review /tmp/review-bundle accept --key /private/operator-review.key > review.json
leanguard-policy verify-review /tmp/review-bundle review.json --key /private/operator-review.key
```

Bundles contain the authoring document, generated Lean, build/audit log, native
inspection, dependency/source provenance, executable, scenario summary and a
manifest of hashes. Source, metadata, dependency and binary changes invalidate
the review. The bundler rejects edits made after compilation and dependency
drift. Full scenario inputs, facts and diagnostics are omitted by default;
`--include-scenario-data` explicitly includes them for a private review. Redacted
bundles identify the private corpus by digest and cannot reproduce its scenarios
without that corpus. Policy source itself may contain sensitive information;
choose an appropriate repository before sharing it.

The local review record binds the bundle digest, accept/reject decision, local OS
user and timestamp with HMAC-SHA256. Its private key must be a 32-byte file with
owner-only permissions. This authenticates the local operator capability, not a
portable identity or an enterprise approval role. Keep that key outside agent
filesystems and tools. For multi-party deployment, use the repository's
authenticated PR review and deployment controls; a shared local key does not
replace those controls. Never commit the key.

## Publication and activation

Put the authoring source, reviewable changes, provenance and bundle digest in a
Git change/PR. Store the exact reviewed executable through the deployment team's
artifact channel. The authoring tools do not merge PRs, publish releases, or
deploy services. The deployment authority verifies the accepted review and
artifact immediately before creating the host:

```python
from pathlib import Path
from leanguard import GuardHost
from leanguard.policy_review import verify_for_activation

artifact = verify_for_activation(bundle_directory, review_record, private_key_path)
host = GuardHost(artifact["domain"], fresh_journal, trusted_adapter,
                 principal=principal, session=session, binary=Path(artifact["binary"]))
```

Protect the bundle against writes between verification and use. Filesystem and
deployment isolation remain assumptions. `GuardHost` continues to reject a journal
bound to a different executable. Keep old bundles, reviews and journals for
audit/rollback; rollback selects the matching old journal or an explicitly fresh
lifecycle. No history migration is implied. A source rebuild needs a new review
even if its scenarios agree with the old binary.

Version 1 is explicit and rejects unknown document versions. There are no silent
format migrations. Future migrations must produce a reviewable source change,
rebuild the native artifact and invalidate old approvals. The bundle records
reproduction inputs and the actual executable digest; byte-identical builds on
different operating systems/toolchains are not claimed.
