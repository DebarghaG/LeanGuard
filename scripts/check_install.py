"""Check an installed platform wheel from outside the source checkout, without Lean."""

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import leanguard
from leanguard import Engine, GuardHost, replay
from leanguard.demo import MemoryTools


def main():
    package = Path(leanguard.__file__).resolve().parent
    binary = package / "bin/leanguard"
    metadata = json.loads((package / "bin/build-details.json").read_text())
    assert metadata["binary_sha256"] == hashlib.sha256(binary.read_bytes()).hexdigest()
    subprocess.run([sys.executable, "-m", "leanguard.cli", "demo"], check=True)
    with tempfile.TemporaryDirectory() as directory:
        tools = MemoryTools()
        with GuardHost(
            "example",
            Path(directory) / "journal.sqlite",
            tools,
            principal="alice",
            session="installed",
        ) as host:
            assert host.engine.binary == binary
            assert not host.execute("write", {"value": "updated"})["allow"]
            assert not tools.calls
            assert host.execute("read", {})["allow"]
            proposal = host.prepare("write", {"value": "initial"})
            host.confirm(proposal.id, True)
            assert (
                host.execute("write", {"value": "initial"}, proposal_id=proposal.id)["outcome"]
                == "success"
            )
            consumed = host.execute("write", {"value": "initial"}, proposal_id=proposal.id)
            assert consumed["reasons"] == ["example.confirm"]
            events = host.events()
        with Engine("example") as engine:
            assert [r["assessment"] for r in replay(engine, events)] == [
                "denied",
                "allowed",
                "allowed",
                "denied",
            ]
        with GuardHost(
            "example",
            Path(directory) / "journal.sqlite",
            tools,
            principal="alice",
            session="installed",
        ) as host:
            assert len(tools.calls) == 2  # Recovery does not execute tools.
    for domain in ("retail", "airline", "telecom"):
        with Engine(domain) as engine:
            assert engine.manifest["schemas"]
    print("Installed wheel: native execution, consent, restart and replay passed.")


if __name__ == "__main__":
    main()
