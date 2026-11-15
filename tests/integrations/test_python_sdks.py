"""Invoke real SDK tools; each integration runs in an isolated dependency job."""

import importlib
import json
import os

import pytest
from leanguard import GuardHost
from leanguard.demo import MemoryTools


async def invoke(framework, host, arguments):
    module = importlib.import_module(f"leanguard.integrations.{framework}")
    tool = module.guarded_tool(host)
    if framework == "strands":
        events = [
            event
            async for event in tool.stream(
                {"toolUseId": "call-1", "name": "guarded_call", "input": arguments}, {}
            )
        ]
        return json.loads(events[-1]["tool_result"]["content"][0]["text"])
    if framework == "langchain":
        from langchain_core.messages import AIMessage
        from langgraph.graph import END, START, MessagesState, StateGraph
        from langgraph.prebuilt import ToolNode

        graph = StateGraph(MessagesState)
        graph.add_node("tools", ToolNode([tool]))
        graph.add_edge(START, "tools")
        graph.add_edge("tools", END)
        result = await graph.compile().ainvoke(
            {
                "messages": [
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": tool.name,
                                "args": arguments,
                                "id": "call-1",
                                "type": "tool_call",
                            }
                        ],
                    )
                ]
            }
        )
        return json.loads(result["messages"][-1].content)
    if framework == "deepagents":
        from deepagents import create_deep_agent
        from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
        from langchain_core.messages import AIMessage, ToolMessage

        class ToolModel(FakeMessagesListChatModel):
            def bind_tools(self, tools, **kwargs):
                return self

        model = ToolModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": tool.name, "args": arguments, "id": "call-1", "type": "tool_call"}
                    ],
                ),
                AIMessage(content="Done"),
            ]
        )
        agent = create_deep_agent(model=model, tools=[tool])
        result = await agent.ainvoke({"messages": [{"role": "user", "content": "Run the tool"}]})
        response = next(m for m in result["messages"] if isinstance(m, ToolMessage))
        return json.loads(response.content)
    if framework == "openai":
        from agents.tool_context import ToolContext

        encoded = json.dumps(arguments)
        context = ToolContext(
            context=None, tool_name=tool.name, tool_call_id="call-1", tool_arguments=encoded
        )
        return await tool.on_invoke_tool(context, encoded)
    if framework == "adk":
        return await tool.run_async(args=arguments, tool_context=None)
    if framework == "microsoft":
        return await tool.invoke(arguments=arguments, skip_parsing=True)
    if framework == "crewai":
        return tool.run(**arguments)
    if framework == "llamaindex":
        return (await tool.acall(**arguments)).raw_output
    if framework == "pydantic":
        from pydantic_ai import RunContext
        from pydantic_ai.models.test import TestModel
        from pydantic_ai.toolsets import FunctionToolset
        from pydantic_ai.usage import RunUsage

        context = RunContext(deps=None, model=TestModel(), usage=RunUsage())
        toolset = FunctionToolset([tool])
        registered = await toolset.get_tools(context)
        return await toolset.call_tool(
            "guarded_call", arguments, context, registered["guarded_call"]
        )
    if framework == "agno":
        from agno.tools.function import FunctionCall

        return (await FunctionCall(function=tool, arguments=arguments).aexecute()).result
    if framework == "haystack":
        return await tool.invoke_async(**arguments)
    if framework == "smolagents":
        return tool(**arguments)
    if framework == "dspy":
        return await tool.acall(**arguments)
    if framework == "camel":
        return await tool.async_call(**arguments)
    if framework == "claude":
        import anyio
        from claude_agent_sdk import create_sdk_mcp_server
        from mcp.client.session import ClientSession
        from mcp.shared.memory import create_client_server_memory_streams

        server = create_sdk_mcp_server("leanguard", tools=[tool])["instance"]
        async with (
            create_client_server_memory_streams() as (client_streams, server_streams),
            anyio.create_task_group() as group,
        ):
            group.start_soon(server.run, *server_streams, server.create_initialization_options())
            async with ClientSession(*client_streams) as client:
                await client.initialize()
                response = await client.call_tool("guarded_call", arguments)
                result = json.loads(response.content[0].text)
            group.cancel_scope.cancel()
        return result
    raise AssertionError(f"missing invocation fixture for {framework}")


@pytest.mark.parametrize(
    "framework,dependency",
    [
        ("strands", "strands"),
        ("langchain", "langgraph"),
        ("deepagents", "deepagents"),
        ("openai", "agents"),
        ("adk", "google.adk"),
        ("microsoft", "agent_framework"),
        ("crewai", "crewai"),
        ("llamaindex", "llama_index.core"),
        ("pydantic", "pydantic_ai"),
        ("agno", "agno"),
        ("haystack", "haystack"),
        ("smolagents", "smolagents"),
        ("dspy", "dspy"),
        ("camel", "camel"),
        ("claude", "claude_agent_sdk"),
    ],
)
async def test_native_tool(framework, dependency, tmp_path):
    if os.environ.get("LEANGUARD_REQUIRE_SDK") == framework:
        importlib.import_module(dependency)
    else:
        pytest.importorskip(dependency)
    adapter = MemoryTools()
    with GuardHost(
        "example", tmp_path / "events.sqlite", adapter, principal="alice", session="sdk"
    ) as host:

        async def call(action, arguments, proposal_id=None):
            payload = {"action": action, "arguments": arguments}
            if proposal_id:
                payload["proposal_id"] = proposal_id
            return await invoke(framework, host, payload)

        denied = await call("write", {"value": "bad"})
        assert not denied["allow"]
        assert set(denied) == {"allow", "request_id", "message"}
        assert adapter.calls == []
        assert (await call("read", {}))["outcome"] == "success"
        proposal = host.prepare("write", {"value": "good"})
        host.confirm(proposal.id, True)
        assert not (await call("write", {"value": "changed"}, proposal.id))["allow"]
        assert (await call("write", {"value": "good"}, proposal.id))["outcome"] == "success"
        assert not (await call("write", {"value": "good"}, proposal.id))["allow"]
        assert adapter.value == "good"
        assert len(adapter.calls) == 2

        def fail(action, arguments):
            raise RuntimeError("private backend diagnostic")

        adapter.execute = fail
        unknown = await call("read", {})
        assert unknown["outcome"] == "unknown"
        assert "error" not in unknown


@pytest.mark.parametrize(
    "framework,dependency",
    [
        ("langchain", "langgraph"),
        ("llamaindex", "llama_index.core"),
        ("haystack", "haystack"),
    ],
)
def test_sync_tool(framework, dependency, tmp_path):
    if os.environ.get("LEANGUARD_REQUIRE_SDK") == framework:
        importlib.import_module(dependency)
    else:
        pytest.importorskip(dependency)
    adapter = MemoryTools()
    with GuardHost(
        "example", tmp_path / "sync.sqlite", adapter, principal="alice", session="sync"
    ) as host:
        tool = importlib.import_module(f"leanguard.integrations.{framework}").guarded_tool(host)
        payload = {"action": "write", "arguments": {"value": "bad"}}
        if framework == "langchain":
            result = tool.invoke(payload)
        elif framework == "llamaindex":
            result = tool.call(**payload).raw_output
        else:
            result = tool.invoke(**payload)
        assert not result["allow"]
        assert not adapter.calls
