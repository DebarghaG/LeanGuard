# Vercel AI SDK and Mastra

These optional clients expose one tool backed by a LeanGuard-owned HTTP
service. The server executes the backend operation under its own admission
lock; JavaScript does not evaluate policy or execute the raw operation.
Requires Node 22 or later. The package is repository-local, not published.

```sh
cd integrations/typescript
npm ci
npm run build
```

Vercel AI SDK 7.0.173 / `@ai-sdk/mcp` 2.0.99:

```ts
import { generateText } from "ai";
import { connectLeanGuard } from "./dist/vercel.js";

const guard = await connectLeanGuard({
  url: process.env.LEANGUARD_URL!, token: process.env.LEANGUARD_MCP_TOKEN!,
});
try {
  const result = await generateText({ model, prompt, tools: guard.tools, maxRetries: 0 });
} finally {
  await guard.close();
}
```

Mastra core 1.83.0 / MCP 2.9.0:

```ts
import { Agent } from "@mastra/core/agent";
import { connectLeanGuard } from "./dist/mastra.js";

const guard = await connectLeanGuard({
  url: process.env.LEANGUARD_URL!, token: process.env.LEANGUARD_MCP_TOKEN!,
});
try {
  const agent = new Agent({ id: "guarded", name: "Guarded", model,
    instructions: "Use guarded tools; report denials and uncertain outcomes.",
    tools: guard.tools });
  const result = await agent.generate(prompt);
} finally {
  await guard.close();
}
```

`model` and `prompt` are application configuration in these examples. Keep the
client alive for the full agent run and close it after outstanding calls finish.
Use an explicit action catalog in the agent instructions. Only `guarded_call`
is exposed (prefixed `leanguard_` by Mastra); approval and policy administration
remain outside model tools. Do not also register a raw tool with the same effects.

Start the service following [the deployment guide](../../docs/mcp-execution-service.md).
Use HTTPS outside loopback; each credential reaches one server-bound identity
and session. Tool arguments cannot choose these bindings. Do not expose backend
credentials to the agent or other tools. Workflow retries, raw tools, code
execution, alternate MCP servers, and platform permissions remain deployment
responsibilities. A lost connection can follow a completed dispatch: reconcile
the server journal before retrying. Request IDs are not idempotency keys.

Arguments are validated and copied before dispatch. Values that JSON would
silently change (including unsafe integers, negative zero, undefined, getters,
sparse arrays, cycles and non-plain objects) are rejected. JavaScript has already
rounded an integer outside its safe range before this client sees it; encode
large quantities as schema-defined strings or use a lossless client. The server
still validates authoritative units and schemas.

`npm test` runs both SDK tool execution paths against a real native LeanGuard
server and a backend spy. It checks denial, approval consumption, unknown
outcomes, and number validation without a model API. It does not certify all
agent/workflow extensions. `LEANGUARD_TEST_PYTHON` selects the fixture Python;
otherwise it uses the repository `.venv`. Install `.[test,mcp]` and build
`lake build leanguard` first. Exact dependency versions and the lockfile are
the tested support set; upgrades require these tests and reviewed lock changes.
