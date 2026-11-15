import { createMCPClient } from "@ai-sdk/mcp";
import { snapshotJson, connection } from "./connection.js";
import type { GuardConnection } from "./connection.js";

export async function connectLeanGuard(options: GuardConnection) {
  const { url, headers } = connection(options);
  const client = await createMCPClient({
    transport: { type: "http", url: url.toString(), headers },
    maxRetries: 0,
  });
  try {
    const available = await client.tools();
    const guarded = available.guarded_call;
    if (!guarded?.execute) throw new Error("LeanGuard guarded_call is unavailable");
    const execute = guarded.execute;
    return {
      tools: {
        guarded_call: {
          ...guarded,
          execute: async (input: Parameters<typeof execute>[0], context: Parameters<typeof execute>[1]) => {
            return execute(snapshotJson(input), context);
          },
        },
      },
      close: () => client.close(),
    };
  } catch (error) {
    await client.close();
    throw error;
  }
}
