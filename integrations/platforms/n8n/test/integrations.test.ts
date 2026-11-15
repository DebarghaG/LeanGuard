import { registerMcpConformance } from "../../../../tests/integrations/mcp_client_suite.js";
import { LeanGuard } from "../src/nodes/LeanGuard/LeanGuard.node.js";
import type { ISupplyDataFunctions } from "n8n-workflow";
import type { DynamicStructuredTool } from "@langchain/core/tools";

registerMcpConformance("n8n", async options => {
  const context = { getCredentials: async () => options } as unknown as ISupplyDataFunctions;
  const supplied = await new LeanGuard().supplyData.call(context, 0);
  const tool = supplied.response as DynamicStructuredTool;
  return { invoke: async input => tool.invoke(input),
    close: async () => { await supplied.closeFunction?.(); } };
});
