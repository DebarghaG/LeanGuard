"""Run from this directory after `lake build` and installing the Python host."""

import sys
import tempfile
from pathlib import Path

from leanguard import Engine, GuardHost, replay

sys.path.insert(0, str(Path(__file__).parent))
from fake_pbs import FakePBS, scenario
from guard import Guard, ThresholdApprover
from pbs_adapter import PBSAdapter

binary = Path(__file__).parent / ".lake/build/bin/alcf-guard"
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    pbs = FakePBS(root / "work")
    pbs.workdir.mkdir()
    adapter = PBSAdapter(call_tool=pbs.call_tool, qstat=pbs.qstat, home=root / "home")
    now = [0]
    with GuardHost(
        "alcf",
        root / "journal.sqlite",
        adapter,
        binary=binary,
        principal="alice",
        session="demo",
        clock=lambda: now[0],
    ) as host:
        guard = Guard(host, ThresholdApprover(480))
        steps = scenario(pbs, guard, lambda t: now.__setitem__(0, t), root / "home")
        events = host.events()
    with Engine("alcf", binary=binary) as engine:
        rows = list(replay(engine, events))
    for (label, payload), row in zip(steps, rows):
        reasons = ", ".join(row["decision"]["reasons"]) or "-"
        print(f"{label:22} {row['assessment']:8} {reasons}")
    print("tool calls that reached PBS:", [name for name, _ in pbs.calls])
