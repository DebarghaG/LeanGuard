"""Run from this directory after `lake build` and installing the Python host."""

import tempfile
from pathlib import Path

from leanguard import Engine, GuardHost, replay
from leanguard.demo import MemoryTools

binary = Path(__file__).parent / ".lake/build/bin/document-guard"
with tempfile.TemporaryDirectory() as directory:
    backend = MemoryTools()  # Replace with an Adapter for the actual backend.
    with GuardHost(
        "documents",
        Path(directory) / "journal.sqlite",
        backend,
        binary=binary,
        principal="alice",
        session="example",
    ) as host:
        assert not host.execute("write", {"value": "changed"})["allow"]
        proposal = host.prepare("write", {"value": "changed"})
        # Deterministic test fixture. A real integration must use a trusted user UI.
        host.confirm(proposal.id, True)
        assert (
            host.execute("write", {"value": "changed"}, proposal_id=proposal.id)["outcome"]
            == "success"
        )
        events = host.events()
    with Engine("documents", binary=binary) as engine:
        assert [row["assessment"] for row in replay(engine, events)] == ["denied", "allowed"]
        print(engine.manifest)
