# MCP execution service

Use LeanGuard's MCP server as the tool execution boundary for clients in other
languages and visual workflow builders. The service owns the backend adapter,
policy executable, journal, principal, and session. Clients receive results;
they never receive an authorization token to execute a raw backend tool later.

Local clients can continue using the existing stdio command. For Streamable HTTP:

```sh
pip install 'leanguard[mcp]'
# Set LEANGUARD_MCP_TOKEN through your secret manager. Generate a URL-safe
# credential with Python's secrets.token_urlsafe(32); never put it in a flow export.
leanguard mcp --transport streamable-http --host 127.0.0.1 --port 8000 \
  --journal ./private/session.sqlite --principal alice --session conversation-1
```

Connect to `http://127.0.0.1:8000/mcp` with an `Authorization: Bearer ...` header.
Every HTTP request requires the configured token. This is service-to-service
authentication using a pre-shared credential, not an OAuth login service. Use
TLS at a trusted reverse proxy for traffic outside the local host. Configure
`--allowed-host your-host.example` for the exact externally visible Host header;
DNS-rebinding and Origin checks remain enabled. Do not expose wildcard hosts.

The command uses the example in-memory backend unless another supported domain
is selected. It is a development example, not persistent production storage.
Production applications construct `GuardHost` with their own adapter and use
`build_http_app` from `leanguard.mcp_http` with their ASGI server:

```python
app = build_http_app(host, token=deployment_secret,
                     allowed_hosts=["guard.example.com"])
```

Keep the host alive for the entire app lifespan. Restore the actual backend
before opening an existing journal; the host replays policy history, not backend
operations. A new in-memory backend must use a fresh journal.

## Authority and lifecycle

One service process binds one principal/session/journal. Anyone possessing its
token has access to that bound session; deploy separate instances and credentials
for separate users or sessions. MCP transport sessions do not create independent
LeanGuard identities. The stateless HTTP transport still uses the same durable
host and its single-writer lock. Horizontal replicas cannot share a journal.

Only `policy_manifest`, `available_tools`, and `guarded_call` are exposed. Native
policy loading, trusted observations, approval, and backend credentials are not
agent endpoints. Register `guarded_call` in the framework and remove raw tools.
Keep `available_tools`/`policy_manifest` only when the agent needs discovery.

Human approval remains in trusted application code. The CLI has no approval UI,
so calls requiring approval are denied. The service does not treat an incoming
framework approval flag as confirmation. See `Proposal.details` and the
[guarantee boundary](guarantees.md).

An HTTP timeout, cancellation, lost connection, or failure to record an outcome
does not establish that the backend did nothing. Do not automatically retry
calls. The journal can retain an unresolved dispatch; reconciliation must be
performed by trusted code. This service does not add idempotent result replay,
an exactly-once guarantee, or a model-accessible reconciliation endpoint.

## Versions and numeric values

MCP negotiates its transport protocol through initialization. LeanGuard's native
protocol and schemas are described by `policy_manifest`; record the reported
engine fingerprint with your deployment. The server owns the executable and
refuses incompatible journal replay. A client must not replace the configured
policy or principal through tool inputs.

JSON numeric fidelity is a caller responsibility. JavaScript clients must reject
unsafe integers before serialization. Send exact amounts in integer minor units
within the language's safe range, or use a backend schema that explicitly accepts
decimal strings. Never silently round a value that a human reviewed. An SDK
transport does not make a lossy language conversion exact.

The HTTP tests verify authentication before dispatch, native denial, admitted
execution, Host validation, and credential validation. Existing MCP tests cover
the tool surface and approved execution. Framework-specific clients must also
test actual discovery and invocation against this server.
