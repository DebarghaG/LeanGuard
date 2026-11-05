"""A fake `pbs_api` for running the PBS MCP server without a scheduler.

`pbs-mcp-demo` never runs `qsub`; it imports `PBSClient` from `pbs_api`. This
module has the surface its tools use. State lives in the JSON file named by
`FAKE_PBS_STATE`, so the check can read it from outside the server subprocess.
Every call is appended to the state's `calls` list.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace


class PBSException(RuntimeError):
    pass


def _load() -> dict:
    path = Path(os.environ["FAKE_PBS_STATE"])
    if path.exists():
        return json.loads(path.read_text())
    return {"next_id": 1000, "jobs": [], "calls": []}


def _save(state: dict) -> None:
    Path(os.environ["FAKE_PBS_STATE"]).write_text(json.dumps(state, indent=2))


class PBSClient:
    def __init__(self, server: str):
        self.server = server
        self.owner = f"{os.environ.get('FAKE_PBS_USER', 'alice')}@login01"

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def _call(self, op: str, **detail) -> dict:
        state = _load()
        state["calls"].append({"op": op, **detail})
        return state

    def submit(self, script: str, queue, attrs: dict) -> str:
        state = self._call("submit", script=script, queue=queue)
        job_id = f"{state['next_id']}.{self.server}"
        state["next_id"] += 1
        state["jobs"].append(
            {
                "name": job_id,
                "attrs": {
                    "Job_Name": attrs.get("Job_Name", "job"),
                    "job_state": "Q",
                    "queue": queue or "debug",
                    "owner": self.owner,
                    "Resource_List": attrs.get("Resource_List", {}),
                    "stats": 0,
                },
            }
        )
        _save(state)
        return job_id

    def stat_jobs(self, job_id: str | None = None, extend=None):
        state = self._call("stat_jobs", job_id=job_id)
        jobs = []
        for job in state["jobs"]:
            if job_id and job["name"] != job_id:
                continue
            if job_id:
                # A job polled by id goes Q, R, F, so the agent's polling loop ends.
                job["attrs"]["stats"] += 1
                job["attrs"]["job_state"] = "QRF"[min(job["attrs"]["stats"], 2)]
            jobs.append(SimpleNamespace(name=job["name"], attrs=dict(job["attrs"])))
        _save(state)
        return jobs

    def _set_state(self, op: str, job_id: str, new_state: str) -> None:
        state = self._call(op, job_id=job_id)
        for job in state["jobs"]:
            if job["name"] == job_id:
                job["attrs"]["job_state"] = new_state
                _save(state)
                return
        _save(state)
        raise PBSException(f"Unknown Job Id {job_id}")

    def delete_job(self, job_id: str, force: bool = False):
        self._set_state("delete_job", job_id, "F")

    def hold_job(self, job_id: str):
        self._set_state("hold_job", job_id, "H")

    def release_job(self, job_id: str):
        self._set_state("release_job", job_id, "Q")

    def stat_queues(self):
        _save(self._call("stat_queues"))
        return [
            SimpleNamespace(
                name=name, attrs={"enabled": "True", "started": "True", "total_jobs": 0}
            )
            for name in ("debug", "prod")
        ]

    def stat_nodes(self):
        _save(self._call("stat_nodes"))
        return [SimpleNamespace(name="x4000", attrs={"state": "free", "np": "208"})]
