package org.leanguard;

import dev.langchain4j.agent.tool.ToolSpecification;
import dev.langchain4j.mcp.McpToolExecutor;
import dev.langchain4j.mcp.client.DefaultMcpClient;
import dev.langchain4j.mcp.client.McpClient;
import dev.langchain4j.mcp.client.transport.http.StreamableHttpMcpTransport;
import dev.langchain4j.service.tool.ToolExecutor;
import java.util.Map;
import java.util.stream.Collectors;

/** An owned client whose tools can be passed to AiServices.builder(...).tools(...). */
public final class LangChain4jGuard implements AutoCloseable {
    private final McpClient client;
    private final Map<ToolSpecification, ToolExecutor> tools;

    public LangChain4jGuard(String url, String token) {
        Connection.validate(url, token);
        var transport = StreamableHttpMcpTransport.builder().url(url)
                .customHeaders(Map.of("Authorization", "Bearer " + token))
                .followRedirects(false).build();
        client = DefaultMcpClient.builder().transport(transport)
                .protocolVersion("2025-11-25").multiRoundTripMaxRetries(0)
                .toolExecutionTimeoutErrorMessage("Outcome unknown; inspect the LeanGuard journal before retrying")
                .build();
        try {
            tools = Map.copyOf(client.listTools().stream()
                    .filter(tool -> tool.name().equals("guarded_call"))
                    .collect(Collectors.toMap(tool -> tool, tool -> new McpToolExecutor(client, "guarded_call"))));
            if (tools.size() != 1) throw new IllegalStateException("LeanGuard guarded_call is unavailable");
        } catch (RuntimeException error) {
            try { client.close(); } catch (Exception cleanup) { error.addSuppressed(cleanup); }
            throw error;
        }
    }

    public Map<ToolSpecification, ToolExecutor> tools() { return tools; }

    @Override
    public void close() throws Exception { client.close(); }
}
