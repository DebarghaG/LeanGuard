import { DynamicStructuredTool } from "@langchain/core/tools";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { NodeConnectionTypes } from "n8n-workflow";
import type { INodeType, INodeTypeDescription, ISupplyDataFunctions, SupplyData } from "n8n-workflow";
import { z } from "zod";

export class LeanGuard implements INodeType {
  description: INodeTypeDescription = {
    displayName: "LeanGuard", name: "leanGuard", group: ["transform"], version: 1,
    description: "Execute covered operations through a LeanGuard-owned backend",
    defaults: { name: "LeanGuard" }, inputs: [], outputs: [NodeConnectionTypes.AiTool],
    credentials: [{ name: "leanGuardApi", required: true }], properties: [],
  };

  async supplyData(this: ISupplyDataFunctions, _itemIndex: number): Promise<SupplyData> {
    const { connection, snapshotJson } = await import("@leanguard/framework-tools/connection");
    const credentials = await this.getCredentials("leanGuardApi");
    const { url, headers } = connection({ url: String(credentials.url), token: String(credentials.token) });
    const client = new Client({ name: "leanguard-n8n", version: "0.1.0" });
    try {
      await client.connect(new StreamableHTTPClientTransport(url, { requestInit: { headers, redirect: "error" } }));
      const available = await client.listTools();
      if (!available.tools.some(tool => tool.name === "guarded_call")) {
        throw new Error("LeanGuard guarded_call is unavailable");
      }
      const tool = new DynamicStructuredTool({
        name: "guarded_call",
        description: "Request one policy-checked operation. Report denials and uncertain outcomes; do not retry them automatically.",
        schema: z.object({ action: z.string().min(1), arguments: z.record(z.string(), z.unknown()), proposal_id: z.string().optional() }),
        func: async input => {
          const result = await client.callTool({ name: "guarded_call", arguments: snapshotJson(input) });
          if (result.isError) throw new Error("LeanGuard protocol error; reconcile the journal before retrying");
          return JSON.stringify(result.structuredContent ?? result.content);
        },
      });
      return { response: tool, closeFunction: async () => { await client.close(); } };
    } catch (error) {
      await client.close();
      throw error;
    }
  }
}
