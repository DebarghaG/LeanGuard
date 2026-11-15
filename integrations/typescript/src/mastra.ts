import { MCPClient } from "@mastra/mcp";
import type { Tool } from "@mastra/core/tools";
import { snapshotJson, connection } from "./connection.js";
import type { GuardConnection } from "./connection.js";

export async function connectLeanGuard(options: GuardConnection): Promise<{
  tools: Record<string, Tool>;
  close: () => Promise<void>;
}> {
  const { url, headers } = connection(options);
  const client = new MCPClient({
    registerProcessHooks: false,
    servers: { leanguard: { url, requestInit: { headers } } },
  });
  try {
    const available = await client.listTools();
    const guarded = available.leanguard_guarded_call;
    if (!guarded?.execute) throw new Error("LeanGuard guarded_call is unavailable");
    const execute = guarded.execute;
    return {
      tools: {
        leanguard_guarded_call: {
          ...guarded,
          execute: async (input: Parameters<typeof execute>[0], context?: Parameters<typeof execute>[1]) => {
            return execute(snapshotJson(input), context);
          },
        },
      },
      close: () => client.disconnect(),
    };
  } catch (error) {
    await client.disconnect();
    throw error;
  }
}
