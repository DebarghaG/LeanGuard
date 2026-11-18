import sys

import pytest

pytest.importorskip("mcp")
from jsonschema import Draft202012Validator
from leanguard import GuardHost
from leanguard.demo import MemoryTools
from leanguard.host import ReadOnlyToolError
from leanguard.mcp_server import build_server
from mcp import Client
from mcp.client.stdio import StdioServerParameters


async def test_mcp_has_no_approval_or_observation_injection_tools(tmp_path):
    adapter = MemoryTools()
    with GuardHost(
        "example", tmp_path / "journal.sqlite", adapter, principal="alice", session="mcp"
    ) as host:
        async with Client(build_server(host)) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert names == {"policy_manifest", "available_tools", "guarded_call"}
            result = await client.call_tool(
                "guarded_call", {"action": "write", "arguments": {"value": "bad"}}
            )
            assert not result.structured_content["allow"]
            assert result.structured_content["message"] == "Tool call denied by policy."
            assert not {"reasons", "errors", "evidence"} & result.structured_content.keys()
            assert adapter.calls == []
            await client.call_tool("guarded_call", {"action": "read", "arguments": {}})
            proposal = host.prepare("write", {"value": "good"})
            host.confirm(proposal.id, True)
            result = await client.call_tool(
                "guarded_call",
                {"action": "write", "arguments": {"value": "good"}, "proposal_id": proposal.id},
            )
            assert result.structured_content["outcome"] == "success"
            assert adapter.value == "good"


async def test_mcp_stdio_transport(tmp_path):
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "leanguard.cli",
            "mcp",
            "--journal",
            str(tmp_path / "stdio.sqlite"),
            "--principal",
            "alice",
            "--session",
            "stdio",
        ],
    )
    async with Client(parameters) as client:
        result = await client.call_tool("policy_manifest", {})
        assert result.structured_content["domain"] == "example"
        result = await client.call_tool(
            "guarded_call", {"action": "write", "arguments": {"value": "denied"}}
        )
        assert not result.structured_content["allow"]
        result = await client.call_tool("guarded_call", {"action": "read", "arguments": {}})
        assert result.structured_content["result"]["value"] == "initial"


async def test_mcp_uses_the_same_private_diagnostic_boundary(tmp_path):
    adapter = MemoryTools()

    def fail(*args):
        raise ReadOnlyToolError("private backend credential")

    adapter.execute = fail
    with GuardHost("example", tmp_path / "journal", adapter, principal="p", session="s") as host:
        async with Client(build_server(host)) as client:
            result = await client.call_tool("guarded_call", {"action": "read", "arguments": {}})
            assert result.structured_content["outcome"] == "failure"
            assert "private" not in str(result.structured_content)
            assert "error" not in result.structured_content


async def test_discovery_contracts_match_wire_results(tmp_path):
    adapter = MemoryTools()
    with GuardHost("example", tmp_path / "contracts", adapter, principal="p", session="s") as host:
        async with Client(build_server(host)) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            validators = {}
            for name, tool in tools.items():
                Draft202012Validator.check_schema(tool.output_schema)
                validators[name] = Draft202012Validator(tool.output_schema)
            assert set(tools["guarded_call"].input_schema["required"]) == {"action", "arguments"}
            manifest = (await client.call_tool("policy_manifest", {})).structured_content
            validators["policy_manifest"].validate(manifest)
            assert manifest == host.engine.manifest
            catalog = (await client.call_tool("available_tools", {})).structured_content
            validators["available_tools"].validate(catalog)
            assert catalog == adapter.tool_contracts()
            assert not adapter.calls
            for action, args, expected in [
                ("write", {"value": "hello"}, False),
                ("read", {}, True),
            ]:
                Draft202012Validator(catalog[action]["parameters"]).validate(args)
                wire = (
                    await client.call_tool("guarded_call", {"action": action, "arguments": args})
                ).structured_content
                validators["guarded_call"].validate(wire)
                assert wire["allow"] is expected
                if expected:
                    Draft202012Validator(catalog[action]["result_schema"]).validate(wire["result"])
                    assert wire["result"] == {"value": "initial"}
                else:
                    assert set(wire) == {"allow", "message", "request_id"}
            assert not validators["guarded_call"].is_valid(
                {"allow": True, "request_id": "r", "outcome": "success"}
            )


@pytest.mark.parametrize(
    "exc, outcome", [(ReadOnlyToolError, "failure"), (RuntimeError, "unknown")]
)
async def test_unsuccessful_call_matches_discovered_schema(tmp_path, exc, outcome):
    adapter = MemoryTools()

    def fail(*args):
        raise exc("private")

    adapter.execute = fail
    with GuardHost("example", tmp_path / "uncertain", adapter, principal="p", session="s") as host:
        async with Client(build_server(host)) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            wire = (
                await client.call_tool("guarded_call", {"action": "read", "arguments": {}})
            ).structured_content
            assert set(wire) == {"allow", "request_id", "outcome"}
            assert wire["allow"] and wire["outcome"] == outcome
            Draft202012Validator(tools["guarded_call"].output_schema).validate(wire)


async def test_legacy_adapter_discovery_keeps_extension_fields(tmp_path):
    class Legacy(MemoryTools):
        def tool_schemas(self):
            return {"legacy": {"parameters": {"type": "object"}, "custom_label": 7}}

    adapter = Legacy()
    with GuardHost("example", tmp_path / "legacy", adapter, principal="p", session="s") as host:
        async with Client(build_server(host)) as client:
            assert (
                await client.call_tool("available_tools", {})
            ).structured_content == adapter.tool_schemas()
