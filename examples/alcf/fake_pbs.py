"""A stand-in for the PBS MCP server and the two in-process tools, for demos and tests."""

from __future__ import annotations

import itertools
from pathlib import Path


class FakePBS:
    def __init__(self, workdir: Path, user: str = "alice"):
        self.workdir, self.user = Path(workdir), user
        self.jobs: list[dict] = []
        self.calls: list[tuple[str, dict]] = []
        self._ids = itertools.count(1000)

    # The adapter's `qstat`: the user's jobs.
    def qstat(self):
        return [dict(job) for job in self.jobs if job["owner"] == self.user]

    # The adapter's `call_tool`: what the real tools would do.
    def call_tool(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        handler = getattr(self, f"tool_{name}", None)
        if handler is None:
            return {"success": False, "error": f"unknown tool {name}"}
        return handler(**arguments)

    def tool_list_queues(self):
        return {"success": True, "queues": [{"name": "debug"}, {"name": "prod"}]}

    def tool_list_jobs(self, **_):
        return {"success": True, "jobs": self.qstat(), "total": len(self.qstat())}

    def tool_get_job_status(self, job_id, history=False):
        for job in self.jobs:
            if job["job_id"] == job_id:
                return {
                    "success": True,
                    "job_id": job_id,
                    "attributes": {"job_state": job["state"]},
                }
        return {"success": False, "error": f"Job {job_id} was not found"}

    def tool_generate_sim_script(self, protein="p53", steps=10000, **_):
        script = self.workdir / "submit_openmm.sh"
        script.write_text(f"#!/bin/bash\nmodule load frameworks\npython sim.py {protein} {steps}\n")
        return {"success": True, "script_path": str(script)}

    def tool_submit_job(self, script_path, queue="debug", node_count=1, walltime="00:10:00", **_):
        if not Path(script_path).exists():
            return {"success": False, "error": f"Script not found: {script_path}"}
        job = {
            "job_id": f"{next(self._ids)}.pbs",
            "owner": self.user,
            "queue": queue,
            "state": "Q",
            "name": Path(script_path).stem,
        }
        self.jobs.append(job)
        return {"success": True, "job_id": job["job_id"], "queue": queue}

    def tool_read_local_file(self, path):
        value = path.split(":", 1)[1] if ":" in path else path
        target = Path(value).expanduser()
        try:
            return {"success": True, "path": str(target), "content": target.read_text()[:16384]}
        except OSError as exc:
            return {"success": False, "path": str(target), "error": str(exc)}


def scenario(pbs: FakePBS, guard, set_time, home: Path):
    """The demo from docs/alcf-integration.md, section 1.8. Returns (step, payload) pairs."""
    home.joinpath(".globus/app/x/alcf_facility_api_app").mkdir(parents=True, exist_ok=True)
    token_cache = home / ".globus/app/x/alcf_facility_api_app/tokens.json"
    token_cache.write_text('{"access_token": "secret"}')
    stdout = pbs.workdir / "job.out"
    stdout.write_text("simulation finished\n")
    leaky = pbs.workdir / "leaky.sh"
    leaky.write_text("#!/bin/bash\nexport API_KEY=abc123def456\npython app.py\n")

    steps = []

    def step(label, time, name, arguments):
        set_time(time)
        steps.append((label, guard.call(name, arguments)))

    script = str(pbs.workdir / "submit_openmm.sh")
    step("list queues", 0, "list_queues", {})
    step("generate script", 1, "generate_sim_script", {"protein": "p53"})
    step("submit before qstat", 2, "submit_job", {"script_path": script, "queue": "debug"})
    step("list jobs", 5, "list_jobs", {})
    step("submit", 6, "submit_job", {"script_path": script, "queue": "debug"})
    step("second debug submit", 10, "submit_job", {"script_path": script, "queue": "debug"})
    step(
        "oversized submit",
        60,
        "submit_job",
        {"script_path": script, "queue": "prod", "node_count": 64, "walltime": "01:00:00"},
    )
    step("read token cache", 61, "read_local_file", {"path": f"x:{token_cache}"})
    step("read job output", 62, "read_local_file", {"path": str(stdout)})
    step("submit leaky script", 100, "submit_job", {"script_path": str(leaky), "queue": "prod"})
    return steps
