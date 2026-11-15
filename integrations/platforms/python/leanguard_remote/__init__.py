"""Remote tools for visual platforms; execution remains in the LeanGuard service."""

import json
import re
from urllib.parse import urlsplit

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def validate_connection(url: str, token: str) -> None:
    parsed = urlsplit(url)
    loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not (parsed.scheme == "https" or (parsed.scheme == "http" and loopback))
    ):
        raise ValueError(
            "Use HTTPS, or HTTP on loopback, without URL credentials or query parameters"
        )
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,}", token):
        raise ValueError("Supply the deployment's URL-safe bearer credential")


async def guarded_call(
    url: str, token: str, action: str, arguments: dict, proposal_id=None
) -> dict:
    """One call, no retries. Transport errors leave the outcome unresolved."""
    validate_connection(url, token)
    if not isinstance(action, str) or not action or not isinstance(arguments, dict):
        raise ValueError("Expected an action and an argument object")
    if proposal_id is not None and not isinstance(proposal_id, str):
        raise ValueError("proposal_id must be a string or null")
    payload = json.loads(
        json.dumps(
            {"action": action, "arguments": arguments, "proposal_id": proposal_id}, allow_nan=False
        )
    )
    async with (
        httpx.AsyncClient(
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(300, connect=30),
            follow_redirects=False,
        ) as http,
        streamable_http_client(url, http_client=http) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool("guarded_call", payload)
        if result.isError:
            raise RuntimeError("LeanGuard protocol error; reconcile the journal before retrying")
        value = result.structuredContent
        if value is None and len(result.content) == 1 and result.content[0].type == "text":
            value = json.loads(result.content[0].text)
        if not isinstance(value, dict) or type(value.get("allow")) is not bool:
            raise RuntimeError("Invalid LeanGuard result; outcome is unresolved")
        return value


async def check_connection(url: str, token: str) -> None:
    """Validate credentials by listing tools; never invoke an operation."""
    validate_connection(url, token)
    async with (
        httpx.AsyncClient(
            headers={"Authorization": f"Bearer {token}"}, timeout=30, follow_redirects=False
        ) as http,
        streamable_http_client(url, http_client=http) as (read, write, _),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        if not any(tool.name == "guarded_call" for tool in (await session.list_tools()).tools):
            raise ValueError("LeanGuard guarded_call is unavailable")
