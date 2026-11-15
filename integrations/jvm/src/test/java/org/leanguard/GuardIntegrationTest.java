package org.leanguard;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import dev.langchain4j.agent.tool.ToolExecutionRequest;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.Comparator;
import java.util.concurrent.TimeUnit;
import java.util.function.Function;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import static org.junit.jupiter.api.Assertions.*;

@Timeout(30)
class GuardIntegrationTest {
    private static final ObjectMapper JSON = new ObjectMapper();

    @Test
    void langchain4j() throws Exception {
        try (var fixture = new Fixture(); var guard = new LangChain4jGuard(fixture.url, Fixture.TOKEN)) {
            assertEquals(1, guard.tools().size());
            var entry = guard.tools().entrySet().iterator().next();
            assertEquals("guarded_call", entry.getKey().name());
            check(fixture, input -> entry.getValue().execute(ToolExecutionRequest.builder()
                    .id("test").name("guarded_call").arguments(input).build(), null));
        }
    }

    @Test
    void springAi() throws Exception {
        try (var fixture = new Fixture(); var guard = new SpringAiGuard(fixture.url, Fixture.TOKEN)) {
            assertEquals(1, guard.tools().length);
            check(fixture, guard.tools()[0]::call);
        }
    }

    @Test
    void deploymentConfiguration() {
        assertThrows(IllegalArgumentException.class, () -> Connection.validate("http://remote.example/mcp", Fixture.TOKEN));
        assertThrows(IllegalArgumentException.class, () -> Connection.validate("https://example.com/mcp?secret=x", Fixture.TOKEN));
        assertThrows(IllegalArgumentException.class, () -> Connection.validate("https://example.com/mcp", "short"));
    }

    private void check(Fixture fixture, Function<String, String> invoke) throws Exception {
        int before = fixture.calls().size();
        assertFalse(result(invoke.apply("""
                {"action":"write","arguments":{"value":"denied"}}
                """)).get("allow").asBoolean());
        assertEquals(before, fixture.calls().size());
        assertEquals("success", result(invoke.apply("""
                {"action":"read","arguments":{"reference":9007199254740993}}
                """)).get("outcome").asText());
        assertEquals(9007199254740993L, fixture.calls().get(before).get(1).get("reference").asLong());
        String approved = "{\"action\":\"write\",\"arguments\":{\"value\":\"approved\"},\"proposal_id\":\"" + fixture.proposal + "\"}";
        assertEquals("success", result(invoke.apply(approved)).get("outcome").asText());
        assertFalse(result(invoke.apply(approved)).get("allow").asBoolean());
        assertEquals("unknown", result(invoke.apply("""
                {"action":"read","arguments":{"simulate_unknown":true}}
                """)).get("outcome").asText());
        assertEquals(before + 3, fixture.calls().size());
    }

    private JsonNode result(String text) throws Exception {
        JsonNode value = JSON.readTree(text);
        return value.isArray() ? JSON.readTree(value.get(0).get("text").asText()) : value;
    }

    private static final class Fixture implements AutoCloseable {
        static final String TOKEN = "test_credential_" + "x".repeat(32);
        final Path directory;
        final Path callsFile;
        final Process process;
        final String url;
        final String proposal;

        Fixture() throws Exception {
            Path root = Path.of(System.getenv().getOrDefault("LEANGUARD_ROOT", "../..")).toAbsolutePath().normalize();
            directory = Files.createTempDirectory("leanguard-jvm-");
            callsFile = directory.resolve("calls.json");
            var builder = new ProcessBuilder(System.getenv().getOrDefault("LEANGUARD_TEST_PYTHON", root.resolve(".venv/bin/python").toString()),
                    root.resolve("tests/integrations/http_fixture.py").toString(), "--calls-file", callsFile.toString())
                    .directory(root.toFile()).redirectError(ProcessBuilder.Redirect.INHERIT);
            builder.environment().put("PYTHONPATH", root.resolve("python").toString());
            builder.environment().put("LEANGUARD_MCP_TOKEN", TOKEN);
            process = builder.start();
            try {
                var reader = new BufferedReader(new InputStreamReader(process.getInputStream()));
                long deadline = System.nanoTime() + Duration.ofSeconds(10).toNanos();
                while (!reader.ready()) {
                    if (!process.isAlive() || System.nanoTime() > deadline) throw new IllegalStateException("Fixture failed to start");
                    Thread.sleep(20);
                }
                var hello = JSON.readTree(reader.readLine());
                url = hello.get("url").asText();
                proposal = hello.get("proposal").asText();
                try (var http = HttpClient.newHttpClient()) {
                    while (true) {
                        try {
                            var response = http.send(HttpRequest.newBuilder(URI.create(url)).timeout(Duration.ofSeconds(1)).GET().build(), HttpResponse.BodyHandlers.discarding());
                            if (response.statusCode() == 401) break;
                        } catch (java.io.IOException ignored) { /* Only poll readiness, never retry calls. */ }
                        if (System.nanoTime() > deadline) throw new IllegalStateException("Fixture readiness timed out");
                        Thread.sleep(20);
                    }
                }
            } catch (Exception error) {
                close();
                throw error;
            }
        }

        JsonNode calls() throws Exception { return JSON.readTree(Files.readString(callsFile)); }

        public void close() throws Exception {
            process.destroy();
            if (!process.waitFor(5, TimeUnit.SECONDS)) process.destroyForcibly().waitFor();
            try (var paths = Files.walk(directory)) {
                for (var path : paths.sorted(Comparator.reverseOrder()).toList()) Files.delete(path);
            }
        }
    }
}
