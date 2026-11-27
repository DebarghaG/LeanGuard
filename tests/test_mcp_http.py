import json

import pytest

pytest.importorskip("mcp")
import httpx2
from leanguard import GuardHost
from leanguard.demo import MemoryTools
from leanguard.mcp_http import build_http_app

TOKEN = "test_credential_" + "x" * 32


@pytest.fixture
def host(tmp_path):
    with GuardHost(
        "example", tmp_path / "http.sqlite", MemoryTools(), principal="alice", session="http"
    ) as host:
        yield host


async def test_http_requires_auth_and_dispatches_only_through_host(host):
    app = build_http_app(host, token=TOKEN)
    headers = {"Accept": "application/json, text/event-stream"}
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "guarded_call",
            "arguments": {"action": "write", "arguments": {"value": "bad"}},
        },
    }
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app), base_url="http://localhost:8000"
        ) as client,
    ):
        assert (await client.post("/mcp", json=payload, headers=headers)).status_code == 401
        headers["Authorization"] = "Bearer wrong"
        assert (await client.post("/mcp", json=payload, headers=headers)).status_code == 401
        assert not host.adapter.calls
        headers["Authorization"] = f"Bearer {TOKEN}"
        response = await client.post("/mcp", json=payload, headers=headers)
        assert response.status_code == 200
        decision = json.loads(response.json()["result"]["content"][0]["text"])
        assert not decision["allow"]
        assert not host.adapter.calls
        payload["params"]["arguments"] = {"action": "read", "arguments": {}}
        response = await client.post("/mcp", json=payload, headers=headers)
        result = response.json()["result"]["structuredContent"]
        assert result["outcome"] == "success"
        assert len(host.adapter.calls) == 1
        # Host and origin checks apply even with a valid token.
        headers["Host"] = "attacker.example"
        assert (await client.post("/mcp", json=payload, headers=headers)).status_code == 421
        assert len(host.adapter.calls) == 1


@pytest.mark.parametrize("token", ["", "short", "x" * 32 + "\n", None])
def test_missing_or_malformed_service_credential_is_rejected(host, token):
    with pytest.raises(ValueError, match="bearer token"):
        build_http_app(host, token=token)
