import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { createInterface } from "node:readline";
import { test } from "node:test";
import { assertJson, connection, snapshotJson } from "../src/connection.js";
import { connectLeanGuard as vercel } from "../src/vercel.js";
import { connectLeanGuard as mastra } from "../src/mastra.js";

const root = resolve(import.meta.dirname, "../../..");
const token = "test_credential_" + "x".repeat(32);

for (const [name, connect] of [["Vercel", vercel], ["Mastra", mastra]] as const) {
  test(`${name}: real MCP execution preserves native decisions`, { timeout: 30_000 }, async () => {
    const directory = await mkdtemp(resolve(tmpdir(), "leanguard-ts-"));
    const callsFile = resolve(directory, "calls.json");
    const server = spawn(process.env.LEANGUARD_TEST_PYTHON ?? resolve(root, ".venv/bin/python"),
      [resolve(root, "tests/integrations/http_fixture.py"), "--calls-file", callsFile],
      { cwd: root, env: { ...process.env, PYTHONPATH: resolve(root, "python"), LEANGUARD_MCP_TOKEN: token },
        stdio: ["ignore", "pipe", "inherit"] });
    const lines = createInterface({ input: server.stdout });
    let client: Awaited<ReturnType<typeof connect>> | undefined;
    try {
      const [line] = await Promise.race([
        once(lines, "line"),
        once(server, "exit").then(() => { throw new Error("Fixture exited before startup"); }),
      ]);
      const { url, proposal } = JSON.parse(line);
      // Readiness polling never sends a tool call.
      for (let attempt = 0; ; attempt++) {
        try { if ((await fetch(url)).status === 401) break; }
        catch (error) { if (attempt === 100) throw error; }
        if (attempt === 100) throw new Error("Fixture startup timed out");
        await new Promise(resolve => setTimeout(resolve, 20));
      }
      client = await connect({ url, token });
      assert.equal(Object.keys(client.tools).length, 1);
      const tool = Object.values(client.tools)[0];
      const invoke = async (input: Record<string, unknown>) => {
        const output = await tool.execute!(input, { toolCallId: "call-1", messages: [] });
        // SDKs may return a structured result or the standard MCP content wrapper.
        if (output && typeof output === "object" && "structuredContent" in output) {
          return output.structuredContent as Record<string, unknown>;
        }
        if (output && typeof output === "object" && "content" in output) {
          return JSON.parse((output.content as { text: string }[])[0].text);
        }
        return output as Record<string, unknown>;
      };
      const before = JSON.parse(await readFile(callsFile, "utf8")).length;
      assert.equal((await invoke({ action: "write", arguments: { value: "denied" } })).allow, false);
      assert.equal(JSON.parse(await readFile(callsFile, "utf8")).length, before);
      assert.equal((await invoke({ action: "read", arguments: {} })).outcome, "success");
      assert.equal((await invoke({ action: "write", arguments: { value: "approved" }, proposal_id: proposal })).outcome, "success");
      assert.equal((await invoke({ action: "write", arguments: { value: "approved" }, proposal_id: proposal })).allow, false);
      await assert.rejects(() => invoke({ action: "read", arguments: { amount: 2 ** 53 } }), TypeError);
      assert.equal((await invoke({ action: "read", arguments: { simulate_unknown: true } })).outcome, "unknown");
      assert.equal(JSON.parse(await readFile(callsFile, "utf8")).length, before + 3);
    } finally {
      await client?.close();
      lines.close();
      if (server.exitCode === null) {
        server.kill("SIGTERM");
        await once(server, "exit");
      }
      await rm(directory, { recursive: true, force: true });
    }
  });
}

test("connection and JSON validation reject lossy or unsafe inputs", () => {
  assert.throws(() => connection({ url: "http://remote.example/mcp", token }));
  assert.throws(() => connection({ url: "https://example.com/mcp", token: "short" }));
  for (const value of [NaN, Infinity, 2 ** 53, -0, undefined, new Date(), Array(2),
    { [Symbol("hidden")]: 1 }, { get amount() { throw new Error("Do not execute getters"); } }]) {
    assert.throws(() => assertJson({ nested: [value] }), TypeError);
  }
  assertJson({ amount: 42, optional: null, text: "exact" });
  const original = { nested: { amount: 42 } };
  const snapshot = snapshotJson(original);
  original.nested.amount = 0;
  assert.equal(snapshot.nested.amount, 42);
});
