# Policy coverage and interpretations

The retail, airline and telecom packs encode part of the English policies from the
τ-bench text domains, pinned at `672227c6b6676edc20d57ea53b7000262aae77b9`. This
page records which parts, how ambiguous clauses were read, and what was left out.

The domain modules under `LeanGuard/Domains/` are the source of truth. Every
compiled rule has an ID, the actions it applies to, named checks and a description
of its source clause, and `leanguard manifest DOMAIN` prints them all. Native input
schemas exist for all 16 retail, 14 airline and 13 telecom assistant tools at this
pin, but having a schema for a tool doesn't mean every rule about that tool is
enforced.

## What is enforced

| Domain | Enforced constraints |
|---|---|
| Common | Known tool and schema, deny on missing facts, correlated identity, one unresolved call at a time, durable admission |
| Retail | Identity lookup before reading or writing customer data; one customer per conversation; profile and order ownership; bound confirmation; previous order observation; pending or delivered eligibility; cancellation reasons; one modification and one exchange per order; replacements must be the same product and in stock, counted with multiplicity; payment method membership, balance and refund destination |
| Airline | Trusted user-supplied identity; user and reservation ownership; bound confirmation and a prior reservation lookup; cancellation rules for timing, flight status, cabin and insurance; updates only to active reservations; 1–5 passengers, with the count fixed after booking; itinerary, cabin, seat and payment checks; booking payment count and total; baggage allowance, add-only baggage and baggage payment; compensation only when requested and eligible, after a change or cancellation for delays, and for the exact amount |
| Telecom | Lookup and ownership; bill and customer observation; payment requests only for an overdue bill with no other bill awaiting payment; resuming only suspended, unexpired lines with no overdue bills; permitted suspension reasons; data refuelling amount and bound confirmation; a trusted travel observation before enabling roaming |

## How facts reach the policy

The Python adapter reads facts from the current benchmark database. It never
looks at task solutions, evaluation criteria, or an `allowed` flag supplied by the
agent.

Money is converted to whole cents and data quantities to thousandths of a GB, and
any conversion that isn't exact raises an error rather than rounding. Airline
timestamps and telecom contract dates follow the benchmark's fixed EST
convention. Flight schedules, including next-day arrivals marked `+1`, become
departure and arrival timestamps for each date. Lean requires every flight to
have a positive duration and to land strictly before the next one departs; there
is no airport-specific minimum connection time. Recorded actual times take
precedence over estimates, and estimates over the schedule. If the timing
evidence is missing, the call is denied.

For telecom, a bill counts as observed only if an earlier successful lookup
returned that customer's bill ID, status and numeric amount. An empty or
truncated list doesn't count as observing a bill it leaves out. This shows the
bill was seen at some point, which isn't the same as showing it is current.

Delay compensation is judged from the snapshot taken just before a successful
change or cancellation, so rebooking a passenger doesn't erase the disruption
that made them eligible. That snapshot has to match the customer, the reservation
and the passenger count. Imported traces that lack it can't establish the
entitlement.

## Interpretation choices

Several clauses could reasonably be read more than one way. In each case below we
chose the stricter reading, which means LeanGuard can reject a workflow that a
looser reading would accept.

- Retail says an order can be "exchanged or modified once". We allow one dispatch
  across all the pending-order modification tools combined, plus one exchange. The
  reservation stands even if the call fails or its outcome is unknown. A per-tool
  reading would allow more.
- Airline confirmation is also required for cancellations and certificates.
- The airline cancellation reason is trusted structured input, and `health` and
  `weather` are the labels that insurance covers. Nothing checks that the stated
  reason is true.
- Updating an airline reservation (`airline.observed`) requires an earlier
  successful `get_reservation_details` call. The response from booking doesn't
  count, so updating a reservation you just created still needs a lookup.
- Airline identity requires a user ID that the user supplied; finding the user
  through a contact lookup isn't enough.
- Telecom refuelling allows a positive amount of at most 2GB per call, and only
  when recorded usage is over the plan limit. The policy text doesn't say when a
  limit would reset, so there is no cumulative refuelling budget; adding one
  would mean choosing a period.
- Telecom suspension reasons must be exactly `overdue bill` or `contract expired`.
  Paraphrases are denied.

## What isn't covered

- The telecom policy mentions changing plans, but the pinned tool set has no
  plan-change tool, and we didn't invent one. Accepting and making payments
  belongs to the user's own tools, so there is no assistant path around it.
- The telecom technical-support manual isn't fully formalized: neither the full
  troubleshooting order, nor what happens on the device, nor eventual recovery.
  User tool calls are observed after they synchronize, and the agent-facing pack
  doesn't check whether the user behaved correctly.
- Nothing inspects the agent's free-text messages. Truthfulness, recommendations,
  "ask before offering", exact wording for transfers, offering insurance
  unprompted, and claims made after payment are all outside what tool admission
  can enforce.
- There is no production approval screen and no rendering of structured quotes.
  A proposal contains the canonical arguments, the current facts and their units.
  Your screen must show the user the action and price that matter; if it hides
  them, the approval no longer means what the policy assumes.
- Input schemas are compiled in Lean, but policy code still reads the current
  arguments through checked JSON accessors. Historical inputs and outputs have
  typed field projections and count, distinct and sum queries. Inferring output
  schemas and a general relational join language are not implemented.
- Lean's proofs don't extend to what the backend does after a call: refunds
  settling, side effects matching the request, inventory staying consistent.

The local model runs and serving measurements are instrumented experiments. They
aren't official benchmark scores, a measured false-denial rate, or a load test.

## Tests

The tests check this subset with allowed and denied examples:

- `LeanGuard/Tests.lean` covers temporal boundaries, interleaved scopes, errors
  under negation, disjunction and projection, default deny, exact counters and
  cancellation edge cases.
- `tests/test_policies.py` exercises individual domain predicates through the
  engine's read-only audit operation, using synthetic facts as fixtures.
- `tests/test_host.py` checks the dispatch boundary and recovery from failures.
- `tests/test_tau.py` runs the real pinned tools. It includes an airline
  cancellation that the unguarded tool accepts and Lean rejects, as well as
  permitted mutations in all three domains.
- `tests/test_mcp.py` checks both in-process and stdio MCP calls.

Passing these tests doesn't show that every English clause is captured or that
every backend mutation is covered. Claims like that would need a clause-by-clause
formal specification and a much larger differential benchmark.

The [Dogwood conformance suite](../scripts/conformance.py) checks the article's
traces separately, against toy trading tools. It doesn't bear on how completely
the τ-bench policies are covered.
