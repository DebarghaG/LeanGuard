"""Load this component through LANGFLOW_COMPONENTS_PATH or the custom editor."""

from typing import Any, ClassVar

from langchain_core.tools import StructuredTool
from lfx.custom import Component
from lfx.io import Output, SecretStrInput, StrInput

from leanguard_remote import guarded_call, validate_connection


class LeanGuardTools(Component):
    display_name = "LeanGuard"
    description = "Execute covered tools through a LeanGuard-owned backend."
    icon = "ShieldCheck"
    name = "LeanGuardTools"
    inputs: ClassVar[list] = [
        StrInput(name="url", display_name="Service URL", required=True),
        SecretStrInput(name="token", display_name="Service credential", required=True),
    ]
    outputs: ClassVar[list] = [
        Output(name="tools", display_name="Guarded tools", method="build_tools")
    ]

    def build_tools(self) -> list[StructuredTool]:
        url, token = self.url, self.token
        validate_connection(url, token)

        async def call(
            action: str, arguments: dict[str, Any], proposal_id: str | None = None
        ) -> dict:
            """Request one policy-checked operation; report denials and uncertain outcomes."""
            return await guarded_call(url, token, action, arguments, proposal_id)

        return [StructuredTool.from_function(name="guarded_call", coroutine=call)]
