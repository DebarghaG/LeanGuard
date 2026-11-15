"""Trusted approval UI browser fixture; no HTTP control-plane backdoors."""

import sys
from pathlib import Path

from leanguard import GuardHost
from leanguard.approval import ApprovalDesk
from leanguard.demo import MemoryTools
from leanguard.workbench import OperatorServer

with GuardHost(
    "example",
    Path(sys.argv[1]) / "journal.sqlite",
    MemoryTools(),
    principal="reviewer",
    session="browser-test",
) as host:
    proposal = host.prepare(
        "write", {"value": "<img src=x onerror=alert(1)>", "reference": 9007199254740993}
    )
    desk = ApprovalDesk(host)
    desk.enqueue(proposal.id)
    with OperatorServer(desk) as server:
        print(server.url, flush=True)
        server.serve_forever()
