# n8n, Dify and Langflow

These repository-owned extensions expose one tool backed by the
[LeanGuard execution service](../../docs/mcp-execution-service.md). They do not
run native operations inside the workflow worker, copy policy semantics, or
grant approval. Credentials and the service URL belong to trusted platform
configuration. Each service binds one principal/session; a platform user ID or
conversation ID does not automatically select another LeanGuard identity.

Only operations routed through the service are covered. Remove raw tools with
equivalent effects and keep backend credentials out of agents, code nodes and
other MCP servers. Disable workflow retries for side effects. An exception,
timeout or disconnect can follow dispatch: reconcile the server journal before
retrying. Request IDs do not provide idempotent execution. Denial and unknown
outcomes are returned to the agent without turning them into permission to retry.

## n8n

The custom tool node uses n8n's `supplyData` extension point and a LangChain
structured tool. Its credential stores URL and bearer token; neither is a
model parameter. Tested with the `n8n-workflow` 2.47.2 library shipped in n8n
2.47.7, LangChain core 1.4.1, and MCP TypeScript SDK 1.32.2. Use Node 24 for the
current workflow library's transitive runtime requirements.

```sh
cd integrations/typescript
npm ci && npm run build
cd ../platforms/n8n
npm ci && npm run build
```

Keep this checkout in the n8n runtime image; the local package dependency points
to `integrations/typescript`. Set `N8N_CUSTOM_EXTENSIONS` to the absolute
`integrations/platforms/n8n/dist` directory, restart n8n, add a **LeanGuard service**
credential, and connect the **LeanGuard** node to an AI Agent's tool input.
Only `guarded_call` is supplied. Use a maintained self-hosted n8n installation;
this private package has not been submitted to the community registry.

Arguments are copied and validated by the shared TypeScript client utilities.
Unsafe integers and other lossy JSON values are rejected. Use schema-defined
strings for large quantities. The pinned n8n library requires Zod 3.25.76, which
currently has an upstream oversized-collection denial-of-service advisory
[GHSA-mrhx-c7xc-m3w5](https://github.com/advisories/GHSA-mrhx-c7xc-m3w5).
This integration does not override that peer with an incompatible major version.
Track the upstream fix before production rollout; the dependency limitation is
also recorded in #35. The node's conformance path is tested, not the complete
n8n editor or every workflow node.

## Dify

The plugin uses `dify-plugin` 0.11.0 and declares Dify 1.19.0 as its minimum
platform version. Build the shared remote-client wheel into the plugin before
packaging; no published LeanGuard package is assumed:

```sh
uv build integrations/platforms/python --wheel --out-dir integrations/platforms/dify/wheels
cd integrations/platforms/dify
# Use Dify's official plugin CLI to package this directory:
dify plugin package .
```

Install the resulting local plugin through Dify's trusted plugin administration
flow, then configure **Service URL** and **Service credential** on its provider.
Enable only **Guarded call** in the agent. `action`, `arguments_json`, and optional
`proposal_id` are model parameters. Arguments are a JSON string so Dify's browser
does not need to round integer values. Credential validation only lists tools;
it never invokes an operation. Do not enable automatic tool retries. Use the
platform's established plugin trust/signature process for deployment.

The plugin manifest, provider loader and real SDK `Tool.invoke` path are tested.
A production Dify deployment and marketplace publication are outside these
tests. SDK deprecation warnings are upstream; the code uses its public APIs.

## Langflow

The component targets Langflow/LFX 1.13.2. Install the shared package in the
Langflow environment:

```sh
pip install './integrations/platforms/python[langflow]'
```

Use the custom component editor with
`python/leanguard_remote/langflow.py`, or place that file in a category directory
under `LANGFLOW_COMPONENTS_PATH`. Configure its URL and secret credential, then
connect **Guarded tools** to the Agent component's Tools input. The generated
`StructuredTool` exposes only action, arguments and proposal ID. Keep service
configuration fixed across the run. Do not expose component configuration as
agent-editable fields. Native Python calls preserve integer digits; browser
flows should use schema-defined strings when integers exceed JavaScript's range.

The component constructor, tool generation and actual asynchronous tool path
are tested using LFX. Tests do not certify the hosted editor or unrelated bundles.

## Verification and upgrades

The Python extensions share one small `leanguard-remote` package pinned to MCP
1.30.0. The server uses MCP 2.2.0 in a separate process/environment; do not combine
their extras. They interoperate over negotiated MCP, with execution authority
remaining on the server. All packages remain local until a reviewed release.

```sh
# After building the native engine and installing .[test,mcp] in the host .venv:
uv venv /tmp/leanguard-platform
uv pip install --python /tmp/leanguard-platform/bin/python \
  -e 'integrations/platforms/python[test,dify]'
LEANGUARD_PLATFORM=dify /tmp/leanguard-platform/bin/python -m pytest \
  -q integrations/platforms/tests/test_python.py
# Repeat in a separate environment with langflow in place of dify.
cd integrations/platforms/n8n && npm test
```

CI requires all three SDKs. Tests use a native server and an independent backend
spy for denial, approval consumption, unknown outcomes, authentication and
number fidelity. They make no model API calls. Dependency updates require the
same tests, reviewed pins/lockfiles, and updated coverage notes. The shared
JavaScript conformance suite also serves Vercel and Mastra.

References: [n8n MCP tools](https://docs.n8n.io/integrations/builtin/cluster-nodes/sub-nodes/n8n-nodes-langchain.toolmcp/),
[Dify tool plugins](https://docs.dify.ai/en/develop-plugin/dev-guides-and-walkthroughs/tool-plugin),
[Langflow custom components](https://docs.langflow.org/components-custom-components).
