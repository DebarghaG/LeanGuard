# Spring AI and LangChain4j

Repository-local Java 21 clients expose only LeanGuard's `guarded_call` using
the framework's native MCP tool execution. The server owns the backend,
snapshot, policy evaluation and journal; there is no Java policy evaluator.
The Maven artifact is not published. Both SDK dependencies are optional to
consumers; applications declare the SDK they use at the tested version.

Spring AI 2.0.2 (`org.springframework.ai:spring-ai-mcp`):

```java
try (var guard = new SpringAiGuard(url, token)) {
    var response = chatClient.prompt(prompt).toolCallbacks(guard.tools()).call().content();
}
```

LangChain4j 1.23.0 (`dev.langchain4j:langchain4j-mcp:1.23.0-beta33`):

```java
try (var guard = new LangChain4jGuard(url, token)) {
    var assistant = AiServices.builder(Assistant.class)
            .chatModel(model).tools(guard.tools()).build();
    var response = assistant.chat(prompt);
}
```

Here `Assistant`, `model`, `chatClient` and `prompt` belong to the application.
Keep clients alive until all calls finish. In Spring, register the owned client
as a bean with a close lifecycle when it should span multiple requests.
Use the server deployment configuration for `url` and `token`; never let an
agent select them. See [service deployment](../../docs/mcp-execution-service.md).
Configure a separate server-bound identity/session for each required isolation
boundary. Framework conversation IDs do not change the server identity.

Use HTTPS outside loopback. No raw backend tool, code executor, or alternate
credential path may bypass LeanGuard for covered effects. Approval uses a
separate trusted application channel. The clients do not retry uncertain
dispatches; configure application retries accordingly. Timeouts, cancellation,
or connection loss can follow execution. Reconcile the server journal before
retrying. LangChain4j's timeout message explicitly reports this uncertainty.
Neither a client exception nor an agent error handler proves absence of effects.

The JSON argument path preserves 64-bit integer values in the pinned SDKs;
tests cover a value above JavaScript's safe integer range. Do not pre-convert
amounts through floating-point types. Native schemas and authoritative units
still determine admission. The LangChain4j client pins MCP 2025-11-25 and
disables multi-round-trip tool resubmission; an SDK/protocol upgrade requires
conformance testing. Spring negotiates with the server using its native client.

```sh
# From the repository root, install .[test,mcp] and build lake build leanguard.
cd integrations/jvm
mvn test
```

Tests run actual framework tool callbacks against the native HTTP fixture and
check zero-effect denial, exact approval consumption, unknown outcomes, and
integer fidelity. They use no model API. `LEANGUARD_TEST_PYTHON` overrides the
repository `.venv/bin/python`; `LEANGUARD_ROOT` overrides the inferred checkout.
The test suite certifies these tool paths, not every agent extension or hosted
workflow. Versions in `pom.xml` are the tested support set; upgrade them in a
reviewed change with passing CI.
