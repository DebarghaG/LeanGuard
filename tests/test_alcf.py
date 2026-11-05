"""Tests for the ALCF example: adapter facts without an engine, and the demo scenario with one."""

import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from leanguard import Engine, GuardHost, ReadOnlyToolError, replay

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/alcf"
sys.path.insert(0, str(EXAMPLE))

from fake_pbs import FakePBS, scenario
from guard import DENIED, Guard, ThresholdApprover, bridge, qstat_from_mcp, unwrap
from pbs_adapter import (
    TOOLS,
    PBSAdapter,
    has_secret,
    is_credential_path,
    node_minutes,
    normalize_path,
    submit_arguments,
    walltime_minutes,
)


def adapter(tmp_path, jobs=(), files=None):
    files = files or {}

    def read_file(path):
        if str(path) not in files:
            raise FileNotFoundError(path)
        return files[str(path)]

    return PBSAdapter(
        call_tool=lambda name, args: {"success": True, "name": name},
        qstat=lambda: list(jobs),
        read_file=read_file,
        home=tmp_path / "home",
    )


def test_walltime_and_node_minutes():
    assert walltime_minutes("01:00:00") == 60
    assert walltime_minutes("00:10:00") == 10
    assert walltime_minutes("00:00:01") == 1
    assert walltime_minutes("90") == 2
    assert node_minutes({"node_count": 4, "walltime": "01:30:00"}) == 360
    with pytest.raises(ValueError):
        walltime_minutes("one hour")
    with pytest.raises(ValueError):
        node_minutes({"node_count": 0})


def test_submit_defaults_match_the_pbs_server():
    normalized = submit_arguments({"script_path": "/x/run.sh"})
    assert normalized["queue"] == "debug"
    assert normalized["node_count"] == 1
    assert normalized["walltime"] == "00:10:00"
    assert submit_arguments({"queue": "", "node_count": "2"})["queue"] == "debug"
    assert submit_arguments({"queue": "", "node_count": "2"})["node_count"] == 2


def test_submit_snapshot_facts(tmp_path):
    jobs = [
        {"job_id": "1.pbs", "state": "Q", "queue": "debug"},
        {"job_id": "2.pbs", "state": "R", "queue": "prod"},
        {"job_id": "3.pbs", "state": "F", "queue": "debug"},
    ]
    files = {"/x/run.sh": "#!/bin/bash\npython app.py\n"}
    snapshot = adapter(tmp_path, jobs, files).snapshot(
        "submit_job", {"script_path": "/x/run.sh", "node_count": 2}, "alice"
    )
    assert snapshot.facts["debug_jobs_active"] == 1
    assert snapshot.facts["node_minutes"] == 20
    assert snapshot.amount == 20
    assert snapshot.facts["script_exists"] is True
    assert snapshot.facts["script_secret_pattern"] is False
    assert snapshot.arguments["queue"] == "debug"
    assert snapshot.units == {"amount": "node-minutes"}


def test_submit_snapshot_marks_missing_script(tmp_path):
    snapshot = adapter(tmp_path).snapshot("submit_job", {"script_path": "/nope.sh"}, "alice")
    assert snapshot.facts["script_exists"] is False
    assert snapshot.facts["script_digest"] == ""


def test_revision_ignores_other_users_but_not_own_jobs_or_script(tmp_path):
    files = {"/x/run.sh": "a"}
    args = {"script_path": "/x/run.sh"}
    base = adapter(tmp_path, [], files).snapshot("submit_job", args, "alice").revision
    assert adapter(tmp_path, [], files).snapshot("submit_job", args, "alice").revision == base
    own = [{"job_id": "1.pbs", "state": "Q", "queue": "debug"}]
    assert adapter(tmp_path, own, files).snapshot("submit_job", args, "alice").revision != base
    edited = adapter(tmp_path, [], {"/x/run.sh": "b"}).snapshot("submit_job", args, "alice")
    assert edited.revision != base


@pytest.mark.parametrize(
    "text",
    [
        "export API_KEY=abc123\n",
        "ALCF_API_TOKEN=AgXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX\n",
        'curl -H "Authorization: Bearer AgAbCdEfGhIjKlMnOpQrStUv"\n',
        "PASSWORD=hunter2\n",
    ],
)
def test_secret_patterns(text):
    assert has_secret(text)


def test_clean_script_has_no_secret():
    assert not has_secret("#!/bin/bash\nmodule load frameworks\npython app.py  # reads API_KEY\n")


def test_credential_paths_after_tool_normalization(tmp_path):
    home = tmp_path / "home"
    cache = home / ".globus/app/x/alcf_facility_api_app/tokens.json"
    cache.parent.mkdir(parents=True)
    cache.write_text("{}")
    # The tool strips a leading "host:" and expands "~". A naive check on the raw
    # string sees nothing; the adapter must judge the resolved path.
    assert is_credential_path(normalize_path(f"aurora:{cache}"), home)
    link = tmp_path / "harmless.txt"
    link.symlink_to(cache)
    assert is_credential_path(normalize_path(str(link)), home)
    assert is_credential_path(home / ".ssh/id_rsa", home)
    assert is_credential_path(tmp_path / "work/server.pem", home)
    assert not is_credential_path(tmp_path / "work/job.out", home)
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("HOME", str(home))
        assert is_credential_path(normalize_path("~/.globus/anything"), home)


def test_file_read_snapshot_binds_to_the_resolved_path(tmp_path):
    home = tmp_path / "home"
    (home / ".globus").mkdir(parents=True)
    target = home / ".globus/tokens.json"
    target.write_text("{}")
    snapshot = adapter(tmp_path).snapshot("read_local_file", {"path": f"h:{target}"}, "alice")
    assert snapshot.arguments["path"] == str(target.resolve())
    assert snapshot.facts["path_is_credential"] is True
    assert snapshot.resource == f"file:{target.resolve()}"


def test_failed_read_is_read_only_error(tmp_path):
    failing = PBSAdapter(
        call_tool=lambda name, args: {"success": False, "error": "not found"},
        qstat=list,
        home=tmp_path,
    )
    with pytest.raises(ReadOnlyToolError):
        failing.execute("get_job_status", {"job_id": "x"})
    assert failing.execute("submit_job", {"script_path": "x"}) == {
        "success": False,
        "error": "not found",
    }


def test_unknown_tool_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        adapter(tmp_path).snapshot("rm_rf", {}, "alice")


def test_threshold_approver_uses_adapter_node_minutes():
    details = {"action": "submit_job", "arguments": {}, "facts": {"node_minutes": 500}}
    proposal = SimpleNamespace(details=details)
    messages = []
    assert not ThresholdApprover(480, log=messages.append)(proposal)
    details["facts"]["node_minutes"] = 480
    assert ThresholdApprover(480, log=messages.append)(proposal)
    assert len(messages) == 2


def test_unwrap_removes_only_the_fastmcp_result_wrapper():
    flat = {"success": True, "jobs": []}
    assert unwrap({"result": flat}) == flat
    assert unwrap(flat) == flat
    assert unwrap({"result": "text"}) == {"result": "text"}
    assert unwrap({"result": flat, "extra": 1}) == {"result": flat, "extra": 1}


def test_bridge_runs_mcp_calls_on_the_loop_and_unwraps():
    seen = []

    async def call_mcp_tool(session, name, arguments_json):
        seen.append((session, name, json.loads(arguments_json)))
        return {"result": {"success": True, "echo": name}}

    custom = {"read_local_file": lambda payload: {"success": True, "custom": json.loads(payload)}}

    async def run():
        call_tool = bridge("session", asyncio.get_running_loop(), call_mcp_tool, custom, timeout=5)
        return await asyncio.to_thread(
            lambda: (
                call_tool("list_jobs", {"job_id": "1"}),
                call_tool("read_local_file", {"path": "x"}),
            )
        )

    mcp_result, custom_result = asyncio.run(run())
    assert mcp_result == {"success": True, "echo": "list_jobs"}
    assert custom_result == {"success": True, "custom": {"path": "x"}}
    assert seen == [("session", "list_jobs", {"job_id": "1"})]


def test_qstat_from_mcp_filters_owner_with_host_suffix():
    jobs = [
        {"job_id": "1.pbs", "owner": "alice@aurora-uan-0001", "state": "Q", "queue": "debug"},
        {"job_id": "2.pbs", "owner": "bob@aurora-uan-0001", "state": "R", "queue": "debug"},
        {"job_id": "3.pbs", "owner": "alice", "state": "F", "queue": "prod"},
    ]
    qstat = qstat_from_mcp(lambda name, args: {"success": True, "jobs": jobs}, "alice")
    assert [job["job_id"] for job in qstat()] == ["1.pbs", "3.pbs"]
    failing = qstat_from_mcp(lambda name, args: {"success": False, "error": "down"}, "alice")
    with pytest.raises(RuntimeError):
        failing()


@pytest.fixture(scope="module")
def downstream(tmp_path_factory):
    project = tmp_path_factory.mktemp("alcf-consumer")
    for path in EXAMPLE.iterdir():
        if path.is_file() and path.name != "lake-manifest.json":
            shutil.copy2(path, project / path.name)
    lakefile = project / "lakefile.toml"
    lakefile.write_text(
        lakefile.read_text().replace('path = "../.."', f"path = {json.dumps(str(ROOT))}")
    )
    (project / ".lake").mkdir()
    (project / ".lake/packages").symlink_to(ROOT / ".lake/packages", target_is_directory=True)
    for command in (["lake", "update"], ["lake", "build"]):
        completed = subprocess.run(
            command, cwd=project, capture_output=True, text=True, check=False
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
    return project / ".lake/build/bin/alcf-guard"


def test_scenario_decisions(downstream, tmp_path):
    pbs = FakePBS(tmp_path / "work")
    pbs.workdir.mkdir()
    home = tmp_path / "home"
    adapter = PBSAdapter(call_tool=pbs.call_tool, qstat=pbs.qstat, home=home)
    now = [0]
    with GuardHost(
        "alcf",
        tmp_path / "journal.sqlite",
        adapter,
        binary=downstream,
        principal="alice",
        session="demo",
        clock=lambda: now[0],
    ) as host:
        # The pack and the adapter must agree on the tool set.
        assert set(host.engine.manifest["schemas"]) == TOOLS
        guard = Guard(host, ThresholdApprover(480, log=lambda _: None))
        steps = scenario(pbs, guard, lambda t: now.__setitem__(0, t), home)
        events = host.events()
    outcomes = {label: payload for label, payload in steps}
    denied = {label for label, payload in steps if payload.get("error") == DENIED}
    assert denied == {
        "submit before qstat",
        "second debug submit",
        "oversized submit",
        "read token cache",
        "submit leaky script",
    }
    assert outcomes["submit"]["job_id"] == "1000.pbs"
    assert "simulation finished" in outcomes["read job output"]["content"]
    assert [name for name, _ in pbs.calls] == [
        "list_queues",
        "generate_sim_script",
        "list_jobs",
        "submit_job",
        "read_local_file",
    ]
    with Engine("alcf", binary=downstream) as engine:
        rows = list(replay(engine, events))
    reasons = {label: row["decision"]["reasons"] for (label, _), row in zip(steps, rows)}
    assert reasons["submit before qstat"] == ["alcf.qstat_first", "alcf.script_settled"]
    assert reasons["second debug submit"] == ["alcf.debug_one", "alcf.debug_spacing"]
    assert reasons["oversized submit"] == ["alcf.budget", "alcf.approved"]
    assert reasons["read token cache"] == ["alcf.credentials"]
    assert reasons["submit leaky script"] == ["alcf.no_secrets"]
    assert all(not rows[i]["decision"]["reasons"] for i in (0, 1, 3, 4, 8))
