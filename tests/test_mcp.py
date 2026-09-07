import sys

import pytest

pytest.importorskip("mcp")
from leanguard import GuardHost
from leanguard.demo import MemoryTools
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
