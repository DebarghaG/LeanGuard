# MCP tool contracts

An MCP client calls one of three tools registered in
[`build_server`](../python/leanguard/mcp_server.py). Application actions such
as `cancel_reservation` are arguments to `guarded_call`. The application
chooses the policy executable, adapter, principal, session, and journal.

| MCP tool | Caller supplies | What runs | Structured result |
| --- | --- | --- | --- |
| `policy_manifest` | `{}` | Reads the manifest that the host loaded from the executable. | Domain, protocol, rule summaries, normalized input schemas, schema depth, declared property labels, and executable SHA-256. Some binaries also include an inspection tree. |
| `available_tools` | `{}` | Reads the connected adapter’s catalog. | An object keyed by action name. Each adapter supplies its own caller-facing argument schema. Catalog membership alone grants no permission. |
| `guarded_call` | `action` (string), `arguments` (object), optional `proposal_id` (string or null) | Takes a fresh snapshot. If a proposal was supplied, checks its binding. Asks Lean to admit the call and reserves an admitted dispatch in the journal before calling `adapter.execute(action, arguments)`. | One of the four cases below. |

### What comes back from a call

| Situation | Fields in the MCP structured result | Meaning |
| --- | --- | --- |
| Denied | `allow: false`, `request_id`, `message` | The host did not dispatch this request. |
| Success | `allow: true`, `request_id`, `outcome: "success"`, `result` | The host recorded completion. The action determines the JSON type and meaning of `result`. |
| Known failure | `allow: true`, `request_id`, `outcome: "failure"` | The adapter reported a read-only failure with no backend change. |
| Unknown outcome | `allow: true`, `request_id`, `outcome: "unknown"` | The backend may have acted. The operator must reconcile the outcome before retrying. |

An invalid MCP invocation or a host exception can produce a tool error instead
of one of these objects. A lost connection can leave the caller without a
reply. The absence of a reply cannot establish whether a dispatch occurred.
Detailed denial reasons and backend exceptions stay on the operator side.
See [the host transaction](../python/leanguard/host.py) and
[the model-facing result filter](../python/leanguard/integrations/call.py).

### Example: replacing the demo document

For the `example` CLI domain, `read` accepts an argument object and returns
`{"value":"…"}` with the current string. `write` requires a string `value`,
replaces that string, and returns the same object shape with its new contents.
The adapter stores one value. An optional `resource` identifies the resource to
the policy and does not select another storage slot. An optional nonnegative integer `amount`
supplies policy units. A successful read is still a dispatch in the journal.
[Demo adapter](../python/leanguard/demo.py)

For retail, airline and telecom, the caller uses the backend's argument names and
units. The adapter validates those arguments, prepares normalized inputs for
Lean, then dispatches the original arguments to the selected τ² tool. For
example, a backend price and the integer minor units in a policy snapshot have
different representations. The adapter returns the backend's value in JSON form.
[τ² adapter](../python/leanguard/tau.py)

### Look up an individual action

Call `available_tools({})` on the server for the domain you want. Use the exact
action name as the key. The stock adapters publish these fields for every action.

| Field | What to look for |
| --- | --- |
| `parameters` | Caller-facing JSON Schema. Check `required`, defaults, nested objects, and accepted types here before constructing `arguments`. |
| `description` | What the registered backend tool is intended to do. |
| `execution` | The Python implementation selected on dispatch. For the benchmark domains this is the method on the installed τ² toolkit. |
| `mutates_backend` | Whether the adapter classifies the action as changing backend state. Even reads can consume a dispatch budget. |
| `result_schema` | JSON Schema for the successful backend value inside `guarded_call.result`. An unconstrained object permits varying keys. A top-level string stays a string even when its contents look like JSON. |

Custom adapters can implement `tool_contracts()` to publish the same fields.
Adapters that only implement `tool_schemas()` keep their existing discovery
entries. A missing field means the adapter hasn't declared it. These entries
describe the adapter; they confer no authority and do not validate the effect
of an external service.

### Airline

The named methods are on `AirlineTools`. All results below are successful
backend values. [Pinned airline implementation](https://github.com/sierra-research/tau2-bench/blob/672227c6b6676edc20d57ea53b7000262aae77b9/src/tau2/domains/airline/tools.py)

| Action | What it executes | Returns |
| --- | --- | --- |
| `book_reservation` | Creates a booking for the supplied passengers and flights and applies its payments. | Reservation object |
| `cancel_reservation` | Marks the reservation cancelled and records refunds in its payment history. | Updated reservation |
| `get_reservation_details` | Looks up a reservation by ID. | Reservation object |
| `get_user_details` | Looks up the customer's profile and reservation IDs. | User object |
| `list_all_airports` | Lists the simulator's supported airports. | Array of airport codes and cities |
| `search_direct_flight` | Looks up direct flights for the route and date. | Array of flights |
| `search_onestop_flight` | Finds connecting flights for the route and date. | Array of two-flight arrays |
| `get_flight_status` | Reads the dated instance of the specified flight. | Status string |
| `send_certificate` | Adds the certificate to the user's payment methods. | Message identifying the certificate and amount |
| `update_reservation_baggages` | Changes the bag counts and records the applicable payment. | Updated reservation |
| `update_reservation_flights` | Replaces the booked flights and cabin and records the applicable payment adjustment. | Updated reservation |
| `update_reservation_passengers` | Replaces passenger details on the booking. | Updated reservation |
| `calculate` | Evaluates the supplied arithmetic expression. | Result as a string |
| `transfer_to_human_agents` | Runs the simulator's handoff stub. | The string `Transfer successful` |

### Retail

The methods are on `RetailTools`. Returns and exchanges create requests that
are visible in the order. [Pinned retail implementation](https://github.com/sierra-research/tau2-bench/blob/672227c6b6676edc20d57ea53b7000262aae77b9/src/tau2/domains/retail/tools.py)

| Action | What it executes | Returns |
| --- | --- | --- |
| `find_user_id_by_email` | Looks up the customer by email. | User ID string |
| `find_user_id_by_name_zip` | Matches first name, last name, and ZIP code. | User ID string |
| `get_user_details` | Reads the customer's profile. | User object |
| `get_order_details` | Reads the order by ID. | Order object |
| `get_product_details` | Reads the product and its variants. | Product object |
| `get_item_details` | Looks up an item variant. | Variant object |
| `list_all_product_types` | Builds an alphabetized name-to-product-ID mapping. | A string containing JSON |
| `cancel_pending_order` | Cancels the order and records the refund to its payment method. | Updated order |
| `exchange_delivered_order_items` | Records the items, replacements, payment method, and price difference for an exchange. | Order with exchange requested |
| `modify_pending_order_address` | Changes the order's shipping address. | Updated order |
| `modify_pending_order_items` | Replaces the selected variants and applies the price difference. | Updated order |
| `modify_pending_order_payment` | Changes the payment method and records the payment adjustments. | Updated order |
| `modify_user_address` | Changes the customer's default address. | Updated user |
| `return_delivered_order_items` | Records which items to return and the refund method. | Order with return requested |
| `calculate` | Evaluates the supplied arithmetic expression. | Result as a string |
| `transfer_to_human_agents` | Runs the simulator's handoff stub. | The string `Transfer successful` |

### Telecom

The methods are on `TelecomTools`. For plain dictionaries, the pinned benchmark
serializer converts numeric scalar fields to strings. For example, the refuel
result's `charge` is a string on the wire. [Pinned telecom implementation](https://github.com/sierra-research/tau2-bench/blob/672227c6b6676edc20d57ea53b7000262aae77b9/src/tau2/domains/telecom/tools.py)

| Action | What it executes | Returns |
| --- | --- | --- |
| `get_customer_by_phone` | Matches a contact or line phone number. | Customer object |
| `get_customer_by_id` | Looks up a customer by ID. | Customer object |
| `get_customer_by_name` | Finds customers matching name and date of birth. | Array of customers |
| `get_details_by_id` | Reads the record identified by the supplied ID. | Customer, line, device, bill, or plan object |
| `get_bills_for_customer` | Reads the customer's bills, newest first, up to the limit. | Array of bills |
| `get_data_usage` | Reads the line, plan allowance, extra data and cycle end. | Object with `line_id`, `data_used_gb`, `data_limit_gb`, `data_refueling_gb`, `cycle_end_date` |
| `suspend_line` | Sets the line to suspended and records the suspension date. | Object with `message` and `line` |
| `resume_line` | Sets the line to active and clears its suspension date. | Object with `message` and `line` |
| `send_payment_request` | Sets the bill to awaiting payment. | Message identifying the bill |
| `enable_roaming` | Enables roaming or reports that it was already enabled. | Status string |
| `disable_roaming` | Disables roaming or reports that it was already disabled. | Status string |
| `refuel_data` | Adds data to the line and a one-time charge to a draft bill. | Object with `message`, `new_data_refueling_gb`, and `charge` |
| `transfer_to_human_agents` | Runs the simulator's handoff stub. | The string `Transfer successful` |
