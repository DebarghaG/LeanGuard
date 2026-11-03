"""Deterministic shared-budget and A2A example; no network or model calls."""

import asyncio
import tempfile
from pathlib import Path

from leanguard import MultiAgentHost
from leanguard.a2a import A2AClient, Peer, PeerFacts
from leanguard.demo import MemoryTools


class ResearchAgent:
    async def request(self, operation, payload):
        return {
            "task": {
                "id": "research-1",
                "contextId": "research-context",
                "status": {"state": "TASK_STATE_WORKING"},
            }
        }


async def main():
    with (
        tempfile.TemporaryDirectory() as directory,
        MultiAgentHost(
            "multiagent.example",
            Path(directory) / "journal.sqlite",
            MemoryTools(),
            principal="tenant/alice",
            session="conversation",
            clock=lambda: 100,
        ) as runtime,
    ):
        planner = runtime.grant(
            "planner",
            workflow="workflow-1",
            actions=["read", "a2a.send"],
            resources=["document"],
            peers=["", "research"],
            calls=10,
            amount=100,
            expires=1000,
        )
        workers = [
            planner.delegate(
                name,
                actions=["read"],
                resources=["document"],
                peers=[""],
                calls=5,
                amount=100,
                expires=1000,
            )
            for name in ["worker-a", "worker-b"]
        ]
        first = workers[0].execute("read", {"amount": 60})
        second = workers[1].execute("read", {"amount": 60})
        assert first["allow"] and not second["allow"]
        print("Shared budget: first 60-unit operation admitted; second denied.")
        client = A2AClient(
            planner,
            {
                "research": Peer(ResearchAgent(), lambda action, envelope: PeerFacts("document")),
            },
        )
        result = await client.send(
            "research",
            {
                "messageId": "research-request",
                "role": "ROLE_USER",
                "parts": [{"data": {"operation": "research", "resource": "document"}}],
            },
        )
        assert result["outcome"] == "success"
        assert client.task("research", "research-1")["state"] == "working"
        print("A2A acknowledgement recorded; the task remains working.")


if __name__ == "__main__":
    asyncio.run(main())
