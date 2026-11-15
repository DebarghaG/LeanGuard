# Integration maintenance and rollout

The supported surface is a registered LeanGuard tool whose implementation owns
the full native admission, journal and backend execution transaction. The rest of
an agent framework does not inherit those guarantees. Keep credentials, raw tools
and approval authority outside model reach. See the shared contract in #70.

## Delivery map and merge order

| Work | Pull request | Dependency |
| --- | --- | --- |
| Framework inventory and execution contract | #70 | main |
| Human review design | #71 | main |
| 15 Python framework registrations | #72 | main |
| Authenticated MCP execution service | #73 | main |
| Vercel and Mastra | #74 | #73 |
| Spring AI and LangChain4j | #75 | #74 |
| n8n, Dify and Langflow | #76 | #75 |
| Native policy inspection | #77 | main |
| Structured authoring and Lean compilation | #78 | #77 |
| Native scenarios and exact artifact review | #79 | #78 |
| Local policy workbench | #80 | #79 |

The approval-screen and maintenance PRs are linked from roadmap issues #32 and
#31. Merge each dependency before its child; retarget child PRs to main once the
base is merged. Keep the maintenance configuration until last, when every listed
package directory exists on main. No PR enables auto-merge.

The 22 active integration tracks meet the 5,000-star threshold recorded in #70.
LangChain and LangGraph form one integration track. Retired/legacy projects were
excluded even when their historical star counts were high. Recheck development
status before adding or renewing a framework; stars alone are insufficient.

## Upgrade policy

Core Python stays dependency-free. Framework dependencies live in optional
extras or separate packages. The Python extras are the version source for the
mandatory SDK matrix. JavaScript lockfiles, Maven properties and the remote
Python package record their validated SDK versions. These are exact tested pins;
no untested version interval is promised. Consequently the current minimum and
maximum supported version are the same. Widening support requires testing both
ends and the newest compatible release in isolated environments.

The weekly [Dependabot configuration](../.github/dependabot.yml) proposes updates
for Python, npm, Maven and Actions. It follows GitHub's
[configuration reference](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference).
Upgrade PRs run the same native conformance jobs; reviewers check release notes,
public APIs, schemas, retry/caching behavior and explicit coverage claims before
merging. Keep framework changes isolated. An upgrade that changes a public API
needs an adapter change and corresponding regression, not a skipped test.

For Dify, update its deployment requirements together with the remote package's
extra, rebuild the local wheel and validate the plugin loader. For n8n, preserve
the exact framework peer compatibility and regenerate its lockfile alongside the
shared TypeScript package as needed. Lean/Lake dependencies are outside
Dependabot's supported ecosystems: review the pinned toolchain and upstream
commits manually, run the full native proof/audit gate, rebuild policy artifacts,
and require fresh human review. Never silently reuse an old journal with a new
executable fingerprint.

## Required evidence

Each framework job calls its actual SDK tool API against the real native engine
and a deterministic backend spy. Denial must produce zero backend effects.
Approvals must bind arguments/state/identity and be consumed on dispatch. Unknown
outcomes must remain uncertain, without automatic retry. Python's async boundary
also checks cancellation while execution is in progress. Shared host tests cover
replay, journal ownership, concurrency, revocation and authority isolation.

The remote suite uses the same authenticated MCP service and shared fixtures
across TypeScript, JVM and visual-platform clients. SDK dependencies are mandatory
in their jobs; an absent SDK cannot turn a claimed integration into a green skip.
Browser CI compiles a real draft, runs native scenarios and reviews an artifact,
with automated accessibility and narrow-screen checks. No live model credentials
are needed. Run `scripts/verify.py` in addition to the affected integration job.

## Explicit limits and follow-up evidence

- Provider-hosted tools, arbitrary code/shell execution, dynamically added raw
  tools and unguarded child agents are outside these registrations' coverage.
- The service binds one trusted principal/session per process. It does not supply
  tenant authentication, durable request-result lookup or exactly-once effects.
  Lost responses require trusted investigation; #34 tracks service expansion.
- SDK conformance is not certification of a production Dify/Langflow/n8n instance
  or marketplace release. Deployment and plugin trust controls still apply.
- n8n's current peer requires Zod 3.25.76, with the upstream constrained-collection
  memory-exhaustion advisory GHSA-mrhx-c7xc-m3w5. #35 tracks the compatible fix;
  do not bypass the peer with an untested major override or claim a clean audit.
- Scenario comparisons are sampled evidence, not equivalence proofs. Full causal
  witness traces and delegated replay are not implemented by the workbench (#67).
- Local HMAC review authenticates the operator capability, not enterprise identity
  or a production deployment role (#68). Protect files between verification/use.
- Non-Lean human usability studies remain open in #66. Automated browser/axe
  checks establish tested interactions, not observed comprehension.
