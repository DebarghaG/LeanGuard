import assert from "node:assert/strict";
import { test } from "node:test";
import { registerMcpConformance } from "../../../tests/integrations/mcp_client_suite.js";
import { assertJson, connection, snapshotJson } from "../src/connection.js";
import { connectLeanGuard as vercel } from "../src/vercel.js";
import { connectLeanGuard as mastra } from "../src/mastra.js";

const token = "test_credential_" + "x".repeat(32);
for (const [name, connect] of [["Vercel", vercel], ["Mastra", mastra]] as const) {
  registerMcpConformance(name, async options => {
    const client = await connect(options);
    assert.equal(Object.keys(client.tools).length, 1);
    const tool = Object.values(client.tools)[0];
    return { invoke: async input => tool.execute!(input, {toolCallId: "test", messages: []}), close: client.close };
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
