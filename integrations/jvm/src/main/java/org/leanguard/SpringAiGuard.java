package org.leanguard;

import io.modelcontextprotocol.client.McpClient;
import io.modelcontextprotocol.client.McpSyncClient;
import io.modelcontextprotocol.client.transport.HttpClientStreamableHttpTransport;
import java.net.http.HttpRequest;
import org.springframework.ai.mcp.SyncMcpToolCallbackProvider;
import org.springframework.ai.tool.ToolCallback;

/** An owned client whose callbacks can be passed to ChatClient's toolCallbacks. */
public final class SpringAiGuard implements AutoCloseable {
    private final McpSyncClient client;
    private final ToolCallback[] callbacks;

    public SpringAiGuard(String url, String token) {
        var uri = Connection.validate(url, token);
        var origin = uri.getScheme() + "://" + uri.getRawAuthority();
        var endpoint = uri.getRawPath().isEmpty() ? "/mcp" : uri.getRawPath();
        var transport = HttpClientStreamableHttpTransport.builder(origin).endpoint(endpoint)
                .requestBuilder(HttpRequest.newBuilder().header("Authorization", "Bearer " + token))
                .resumableStreams(false).openConnectionOnStartup(false).build();
        client = McpClient.sync(transport).build();
        try {
            client.initialize();
            callbacks = SyncMcpToolCallbackProvider.builder().mcpClients(client)
                    .toolFilter((connection, tool) -> tool.name().equals("guarded_call"))
                    .build().getToolCallbacks();
            if (callbacks.length != 1) throw new IllegalStateException("LeanGuard guarded_call is unavailable");
        } catch (RuntimeException error) {
            try { client.close(); } catch (Exception cleanup) { error.addSuppressed(cleanup); }
            throw error;
        }
    }

    public ToolCallback[] tools() { return callbacks.clone(); }

    @Override
    public void close() { client.close(); }
}
