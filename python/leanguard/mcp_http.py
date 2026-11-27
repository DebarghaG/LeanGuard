"""Authenticated MCP execution for one trusted principal/session per process."""

import hmac
import re

from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from .mcp_server import build_server


class _BearerAuth:
    def __init__(self, app, *, token):
        self.app = app
        self.expected = f"Bearer {token}".encode("ascii")

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            values = [value for key, value in scope["headers"] if key.lower() == b"authorization"]
            if len(values) != 1 or not hmac.compare_digest(values[0], self.expected):
                response = JSONResponse(
                    {"error": "unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def build_http_app(host, *, token: str, allowed_hosts: list[str] | None = None):
    """Build a Streamable HTTP app with a deployment-supplied bearer credential.

    Generate the credential with secrets.token_urlsafe(32). This is a fixed
    service credential, not an OAuth authorization server or multi-tenant login.
    The token grants access only to this host's already-bound principal/session.
    Keep the host alive for the application's full lifespan.
    """
    if not isinstance(token, str) or re.fullmatch(r"[A-Za-z0-9_-]{32,}", token) is None:
        raise ValueError("supply a URL-safe bearer token of at least 32 characters")
    server = build_server(host)
    app = server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts or ["127.0.0.1:*", "localhost:*", "[::1]:*"],
            allowed_origins=[],
        ),
    )
    app.add_middleware(_BearerAuth, token=token)
    return app
