import threading
from copy import deepcopy

from .engine import digest
from .host import Snapshot


class MemoryTools:
    """Small deterministic MCP backend for exercising the enforcement protocol."""

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
