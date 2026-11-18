import threading
from copy import deepcopy

from .engine import digest
from .host import Snapshot


class MemoryTools:
    """A small in-memory backend for demos and tests."""

    def __init__(self):
        self.lock = threading.RLock()
        self.value = "initial"
        self.calls = []

    def snapshot(self, action, arguments, customer):
        return Snapshot(
            arguments.get("resource", "document"),
            digest(self.value),
            {},
            deepcopy(arguments),
            arguments.get("amount", 0),
        )

    def execute(self, action, arguments):
        self.calls.append((action, deepcopy(arguments)))
        if action == "write":
            self.value = arguments["value"]
        return {"value": self.value}

    def mutating(self, action):
        return action != "read"

    def tool_schemas(self):
        return {
            "read": {"description": "Read a document", "parameters": {"type": "object"}},
            "write": {
                "description": "Write a document after approval and read",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
            },
        }

    def tool_contracts(self):
        contracts = self.tool_schemas()
        # Demo subclasses can dispatch unrelated tools (for example, the trading adapter).
        if (
            type(self).execute is not MemoryTools.execute
            or type(self).tool_schemas is not MemoryTools.tool_schemas
        ):
            return contracts
        for action, entry in contracts.items():
            params = entry["parameters"].setdefault("properties", {})
            params["resource"] = {
                "type": "string",
                "default": "document",
                "description": "Resource label used by the policy. The demo stores one value.",
            }
            params["amount"] = {"type": "integer", "minimum": 0, "default": 0}
            entry.update(
                description=(
                    "Replace the stored string and return its new value."
                    if action == "write"
                    else "Return the currently stored string."
                ),
                execution="leanguard.demo.MemoryTools.execute",
                mutates_backend=self.mutating(action),
                result_schema={
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
            )
        return contracts
