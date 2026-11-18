# MCP tool contracts

An MCP client calls one of three tools registered in
[`build_server`](../python/leanguard/mcp_server.py). Application actions such
as `cancel_reservation` are arguments to `guarded_call`. The application
chooses the policy executable, adapter, principal, session, and journal.

| MCP tool | Caller supplies | What runs | Structured result |
| --- | --- | --- | --- |
| `policy_manifest` | `{}` | Reads the manifest that the host loaded from the executable. | Domain, protocol, rule summaries, normalized input schemas, schema depth, reported proof names, and executable SHA-256. Some binaries also include an inspection tree. |
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
the policy and does not select another storage slot. An optional integer `amount`
supplies policy units. A successful read is still a dispatch in the journal.
[Demo adapter](../python/leanguard/demo.py)

For retail, airline and telecom, the caller uses the backend's argument names and
units. The adapter validates those arguments, prepares normalized inputs for
Lean, then dispatches the original arguments to the selected τ² tool. For
example, a backend price and the integer minor units in a policy snapshot have
different representations. The adapter returns the backend's value in JSON form.
[τ² adapter](../python/leanguard/tau.py)
