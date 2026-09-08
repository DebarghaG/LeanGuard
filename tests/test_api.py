"""Public runtime/replay contracts and genuinely separate Lean consumer builds."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from leanguard import Engine, GuardHost, audit, replay
from leanguard.demo import MemoryTools

ROOT = Path(__file__).resolve().parents[1]


def event(id="request", kind="request", time=100, **fields):
    return {
        "id": id,
        "kind": kind,
        "time": time,
        "principal": "alice",
        "session": "one",
        "action": "write",
        "resource": "document",
        "binding": "binding",
        "amount": 0,
        "input": {"value": "initial"},
        "facts": {},
        **fields,
    }


def test_audit_is_read_only_and_reports_missing_evidence():
    with Engine("example") as engine:
        version = engine.version
        result = audit(engine, event())
        assert result["assessment"] == "denied"
        assert "example.confirm" in result["decision"]["reasons"]
        assert (
            audit(engine, event(), history_complete=False)["assessment"] == "insufficient_evidence"
        )
        request = event()
        del request["facts"]
        assert audit(engine, request)["missing_evidence"] == ["missing_facts"]
        assert engine.version == version
        assert engine.request({"op": "status", "version": version})["events"] == 0


def test_replay_preserves_recorded_effects_after_denial():
    # The first write lacks both read evidence and approval. The recorded read that
    # follows still supplies evidence to the later call; replay executes nothing.
    events = [
        event("first"),
        event("read", "success", action="read"),
        event("approval", "confirmed"),
        event("second"),
    ]
    with Engine("example") as engine:
        results = list(replay(engine, events))
        assert [r["assessment"] for r in results] == ["denied", "allowed"]
        assert "first" in results[1]["decision"]["evidence"]
        assert engine.version == 0
    events[1]["missing_evidence"] = ["source omits earlier dispatches"]
    with Engine("example") as engine:
        assert list(replay(engine, events))[1]["assessment"] == "insufficient_evidence"


def test_replay_snapshots_reused_importer_buffer():
    def records():
        buffer = event("read", "success", action="read")
        yield buffer
        buffer.update(event("approval", "confirmed"))
        yield buffer
        buffer.update(event("write"))
        yield buffer

    with Engine("example") as engine:
        assert next(replay(engine, records()))["assessment"] == "allowed"


@pytest.mark.parametrize(
    "events",
    [
        [event(time=True)],
        [event(kind="response")],
        [event("later", time=101), event(time=100)],
        [event(facts=[])],
    ],
)
def test_replay_rejects_ambiguous_or_malformed_records(events):
    with Engine("example") as engine, pytest.raises(ValueError):
        list(replay(engine, events))


def test_runtime_and_exported_replay_agree(tmp_path):
    with GuardHost(
        "example",
        tmp_path / "journal.sqlite",
        MemoryTools(),
        principal="alice",
        session="one",
        clock=lambda: 100,
    ) as host:
        denied = host.execute("write", {"value": "initial"}, request_id="denied")
        read = host.execute("read", {}, request_id="read")
        proposal = host.prepare("write", {"value": "initial"})
        host.confirm(proposal.id, True)
        written = host.execute(
            "write", {"value": "initial"}, request_id="written", proposal_id=proposal.id
        )
        consumed = host.execute(
            "write", {"value": "initial"}, request_id="consumed", proposal_id=proposal.id
        )
        events = host.events()
    with Engine("example") as engine:
        rows = list(replay(engine, events))
    for live, row in zip([denied, read, written, consumed], rows, strict=True):
        assert live["request_id"] == row["request_id"]
        assert {key: live[key] for key in row["decision"]} == row["decision"]


def test_generic_host_does_not_interpret_benchmark_tool_names(tmp_path):
    with GuardHost(
        "example", tmp_path / "journal.sqlite", MemoryTools(), principal="alice", session="one"
    ) as host:
        host.events = lambda: [
            event(kind="success", action="get_customer_by_id", resource="untrusted_customer")
        ]
        assert host.customer() == ""
        host.events = lambda: [event(kind="identity", resource="trusted_customer")]
        assert host.customer() == "trusted_customer"


def test_custom_identity_resolver_gets_only_current_subject_events(tmp_path):
    class Tools(MemoryTools):
        def resolve_identity(self, events):
            assert [e["id"] for e in events] == ["current"]
            return "employee-7"

    with GuardHost(
        "example", tmp_path / "journal.sqlite", Tools(), principal="alice", session="one"
    ) as host:
        host.events = lambda: [
            event("current"),
            event("foreign", principal="bob"),
            event("other_session", session="two"),
        ]
        assert host.customer() == "employee-7"


def test_manifest_carries_compiled_schema_and_binary_identity():
    with Engine("example") as engine:
        assert engine.manifest["engine_sha256"] == engine.fingerprint
        assert engine.manifest["protocol"] == 1
        assert engine.manifest["schemas"]["write"]["required"] == ["value"]


@pytest.fixture(scope="module")
def downstream(tmp_path_factory):
    project = tmp_path_factory.mktemp("policy-consumer")
    source = ROOT / "examples/custom_policy"
    for path in source.iterdir():
        if path.is_file() and path.name != "lake-manifest.json":
            shutil.copy2(path, project / path.name)
    lakefile = project / "lakefile.toml"
    lakefile.write_text(
        lakefile.read_text().replace('path = "../.."', f"path = {json.dumps(str(ROOT))}")
    )
    (project / ".lake").mkdir()
    (project / ".lake/packages").symlink_to(ROOT / ".lake/packages", target_is_directory=True)
    lake = ["lake"]
    for command in (lake + ["update"], lake + ["build"]):
        completed = subprocess.run(
            command, cwd=project, capture_output=True, text=True, check=False
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
    return project, lake


def test_external_verified_policy_runtime_and_proof(downstream, tmp_path):
    project, _ = downstream
    binary = project / ".lake/build/bin/document-guard"
    tools = MemoryTools()
    with GuardHost(
        "documents",
        tmp_path / "journal.sqlite",
        tools,
        binary=binary,
        principal="alice",
        session="one",
        clock=lambda: 100,
    ) as host:
        assert host.engine.manifest["properties"] == ["DocumentGuard.safe"]
        assert not host.execute("write", {"value": "initial"})["allow"]
        assert not tools.calls
        proposal = host.prepare("write", {"value": "initial"})
        host.confirm(proposal.id, True)
        assert host.execute("write", {"value": "initial"}, proposal_id=proposal.id)["allow"]
        assert not host.execute("write", {"value": "initial"}, proposal_id=proposal.id)["allow"]
        assert len(tools.calls) == 1


@pytest.mark.parametrize(
    "declaration, expected",
    [
        ("theorem bad : False := by sorry", "sorryAx"),
        ("axiom foreign : False\ntheorem bad : False := foreign", "foreign"),
    ],
)
def test_downstream_audit_rejects_unfinished_and_axiomatic_proofs(
    downstream, declaration, expected
):
    project, lake = downstream
    path = project / "Rejected.lean"
    path.write_text(
        "import LeanGuard.Audit\nnamespace Consumer\n"
        + declaration
        + "\nend Consumer\nrun_cmd do\n  LeanGuard.Audit.check #[``Consumer.bad] #[`Consumer]\n"
    )
    result = subprocess.run(
        lake + ["env", "lean", str(path)], cwd=project, capture_output=True, text=True, check=False
    )
    assert result.returncode != 0
    assert "nonstandard axioms" in result.stdout and expected in result.stdout
