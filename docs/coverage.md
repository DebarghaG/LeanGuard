# Policy coverage and interpretations

Baseline: τ-bench text domains at `672227c6b6676edc20d57ea53b7000262aae77b9`.
Every compiled rule has an ID, action scope, named checks, and source description;
`leanguard manifest DOMAIN` prints that registry. The domain modules are the executable
source of truth. Native schemas cover all 16 retail, 14 airline, and 13 telecom
assistant tools at this pin. Schema coverage is not full semantic coverage.

## Implemented safety subset

| Domain | Enforced constraints |
|---|---|
| Common | Known tool/schema, fail-closed facts, correlated identity, serialized unresolved calls, durable admission |
| Retail | Identity lookup before customer reads/writes; one customer per conversation; profile/order ownership; bound confirmation; previous order observation; pending/delivered eligibility; cancellation reasons; one-shot modifications/exchanges; same-product available replacements with multiplicity; payment membership/balance and refund destination |
| Airline | Trusted user-supplied identity; user/reservation ownership; bound confirmation and reservation observation; cancellation time/flight/cabin/insurance rules; active reservation updates; 1–5 passengers; fixed passenger count; itinerary/cabin/seat/payment checks; booking payment count/total; baggage allowance/add-only/payment checks; requested compensation, eligibility, preceding change/cancel for delays, exact amount |
| Telecom | Lookup and ownership; bill/customer observation; overdue-only payment request and no other awaiting bill; resume only suspended/unexpired lines with no overdue bills; permitted suspension reasons; data usage/refueling amount and bound confirmation; trusted travel observation before enabling roaming |

The Python adapter extracts current database facts but never reads task solutions,
evaluation criteria, or an agent-provided `allowed` bit. Money is normalized exactly to
cents and GB quantities to thousandths; inexact conversion raises an error. Aircraft
timestamps and telecom contract dates use the benchmark's fixed EST convention.

## Explicit interpretations and remaining gaps

- Retail's generic “exchange or modify once per order” is interpreted conservatively
  as one dispatch across all pending-order modification tools, plus one exchange
  dispatch. The reservation survives an unknown or failed outcome. This can reject
  workflows accepted by a narrower, per-tool interpretation.
- Airline confirmation also covers cancellations and certificates. This is a
  conservative confirmation scope. The cancellation reason is trusted structured
  input; `health` and `weather` are canonical covered insurance labels. This does not
  establish that the reported reason is factually true.
- Telecom refueling currently enforces a positive amount no greater than 2GB **per
  call**, and that recorded usage exceeds the plan limit. The prose does not state an
  explicit reset period; a cumulative refill budget needs a chosen period and policy.
- Telecom suspension reasons use canonical strings `overdue bill` and `contract
  expired`; arbitrary paraphrases are denied. This is a structured interface choice.
- Telecom's main policy refers to changing plans, but the pinned assistant tool set
  has no plan-change tool. No synthetic tool was added. Payment acceptance and actual
  payment belong to the independent user-tool role, not an assistant bypass.
- The telecom technical-support manual's complete troubleshooting order, device-side
  effects, and eventual recovery are not fully formalized. User tool calls are observed
  after synchronization; the agent-facing pack does not prove user behavior correct.
- No free-form conversation interceptor is implemented. Truthfulness, recommendations,
  “ask before offering,” exact transfer wording, user-message/tool overlap, insurance
  solicitation, and post-payment claims are not guaranteed merely by tool admission.
- Full structured quote rendering and a production confirmation UI are not included.
  Proposals contain canonical arguments, current facts, and declared units. Integrators
  must faithfully display the relevant action and price details; hiding them breaks
  the consent assumption.
- Input schemas are compiled in Lean but contexts still use checked JSON accessors.
  Historical inputs and outputs now have typed field projections and count/distinct/sum
  queries. General output-schema inference and a first-order relational join language
  remain future work.
- The real backend's postconditions (refund settlement, side-effect fidelity, external
  inventory consistency) are outside the generic Lean proof. The local model pilot
  and serving probes are instrumented experiments, not a complete benchmark score,
  independently established false-denial rate, or production load test.

## Test levels

`LeanGuard/Tests.lean` checks temporal boundaries, scoped interleaving, errors under
negation/disjunction/projection, default deny, exact counters, and cancellation edges.
`tests/test_policies.py` calls the native read-only audit operation to exercise specific
domain predicates; its synthetic facts are test fixtures, not trusted runtime input.
`tests/test_host.py` checks the dispatch boundary and recovery/failure cases.
`tests/test_tau.py` exercises real pinned tools, including an airline cancellation that
the unguarded tool accepts but Lean rejects, and permitted retail/airline/telecom
mutations. `tests/test_mcp.py` checks both in-process and stdio calls.

These levels demonstrate the safety subset with positive and negative cases. They do
not establish semantic completeness of every English clause or exhaustive coverage
of every backend mutation. Such claims need a clause-by-clause formal specification
and a larger differential benchmark campaign.

The additional [Dogwood conformance suite](dogwood-conformance.md) covers all supplied
article traces separately from the benchmark domain policies; its toy trading tools
do not expand claims about τ-bench's English-policy completeness.
