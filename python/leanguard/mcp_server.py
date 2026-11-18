"""MCP server for guarded tool calls. Approval happens out of band, in host code."""

from __future__ import annotations

from typing import Annotated, Any, Literal, NotRequired

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import ConfigDict, Field, RootModel, with_config
from typing_extensions import TypedDict

from .integrations.call import FAILURE_MESSAGE, GuardedCallError, bind_guarded_call


@with_config(ConfigDict(extra="allow"))
class PolicyManifest(TypedDict):
    domain: str
    protocol: int
    rules: list[dict[str, Any]]
    schemas: NotRequired[dict[str, Any]]
    schema_max_depth: NotRequired[int]
    properties: NotRequired[list[str]]
    inspection: NotRequired[dict[str, Any]]
    engine_sha256: str


@with_config(ConfigDict(extra="allow"))
class ActionContract(TypedDict, total=False):
    description: str
    parameters: dict[str, Any]
    execution: str
    mutates_backend: bool
    result_schema: dict[str, Any]


class Denied(TypedDict):
    allow: Literal[False]
    request_id: str
    message: str


class Succeeded(TypedDict):
    allow: Literal[True]
    request_id: str
    outcome: Literal["success"]
    result: Any


class Unsuccessful(TypedDict):
    allow: Literal[True]
    request_id: str
    outcome: Literal["failure", "unknown"]


class GuardedResult(RootModel[Denied | Succeeded | Unsuccessful]):
    # MCP requires an object at the top level. A bare union adds a "result" wrapper in the SDK.
    model_config = ConfigDict(json_schema_extra={"type": "object"})


def build_server(host, approval=None):
    server = MCPServer("LeanGuard")
    execute = bind_guarded_call(host)

    @server.tool(structured_output=True, annotations=ToolAnnotations(read_only_hint=True))
    def policy_manifest() -> PolicyManifest:
        """Read the loaded policy's rules, normalized input schemas and executable fingerprint.

        Takes no arguments. This reads the host's manifest without evaluating a call or running
        a backend tool. A listed action still has to pass its rules at call time.
        """
        return host.engine.manifest

    @server.tool(structured_output=True, annotations=ToolAnnotations(read_only_hint=True))
    def available_tools() -> dict[str, ActionContract]:
        """Read the backend's action catalog. Takes no arguments and runs no backend action.

        Keys are action names for guarded_call. Each entry can describe the caller's arguments,
        the handler and its effects, and the JSON value returned on success. Older adapters
        may supply only an input description.
        """
        contracts = getattr(host.adapter, "tool_contracts", None)
        return contracts() if contracts is not None else host.adapter.tool_schemas()

    @server.tool(structured_output=True)
    def guarded_call(
        action: Annotated[str, Field(description="Action name from available_tools.")],
        arguments: Annotated[
            dict[str, Any], Field(description="Original backend arguments for this action.")
        ],
        proposal_id: Annotated[
            str | None, Field(description="ID of an existing proposal for this call.")
        ] = None,
    ) -> GuardedResult:
        """Ask the host to run one backend action under its current policy.

        The host checks the request against current state and reserves an admitted dispatch
        before invoking the adapter. Denial returns a request ID and message. Success also
        returns the backend value. An admitted call can fail or have an unknown outcome.
        Check unknown outcomes with the operator before retrying. A proposal ID supplies no
        approval of its own.
        """
        try:
            if approval is not None and proposal_id is None and host.adapter.mutating(action):
                proposal = host.prepare(action, arguments)
                host.confirm(proposal.id, approval(proposal))
                proposal_id = proposal.id
        except Exception:  # noqa: BLE001 -- SDK error messages must not expose trusted diagnostics.
            raise GuardedCallError(FAILURE_MESSAGE) from None
        return GuardedResult(execute(action, arguments, proposal_id))

    return server
