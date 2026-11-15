"""Dify tool/provider classes; credentials are never model parameters."""

import asyncio
import json

from dify_plugin import Tool, ToolProvider

from leanguard_remote import check_connection, guarded_call


class LeanGuardProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict) -> None:
        asyncio.run(check_connection(credentials["url"], credentials["token"]))


class LeanGuardTool(Tool):
    def _invoke(self, tool_parameters: dict):
        # A JSON string avoids Dify UI/JavaScript rounding large numeric arguments.
        arguments = json.loads(tool_parameters["arguments_json"])
        value = asyncio.run(
            guarded_call(
                self.runtime.credentials["url"],
                self.runtime.credentials["token"],
                tool_parameters["action"],
                arguments,
                tool_parameters.get("proposal_id") or None,
            )
        )
        yield self.create_json_message(value)
