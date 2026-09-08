import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from leanguard import Engine, EngineError, GuardHost
from leanguard.demo import MemoryTools


class FaultyTools(MemoryTools):
    fail = False

    def execute(self, action, arguments):
        if self.fail:
            self.calls.append((action, arguments.copy()))
            raise RuntimeError("simulated uncertain outcome")
        return super().execute(action, arguments)


@pytest.fixture
def adapter():
    return FaultyTools()


@pytest.fixture
def host(tmp_path, adapter):
    with GuardHost(
        "example",
        tmp_path / "events.sqlite",
        adapter,
        principal="alice",
        session="one",
        clock=lambda: 100,
    ) as host:
        yield host


def approved(host, value="new"):
    assert host.execute("read", {})["allow"]
    proposal = host.prepare("write", {"value": value})
    host.confirm(proposal.id, True)
    return proposal


def test_denied_write_never_reaches_tool(host, adapter):
    result = host.execute("write", {"value": "new"})
    assert not result["allow"]
    assert "example.confirm" in result["reasons"]
    assert "example.read_first" in result["reasons"]
    assert adapter.calls == []
    assert adapter.value == "initial"


def test_valid_workflow(host, adapter):
    proposal = approved(host)
    result = host.execute("write", {"value": "new"}, proposal_id=proposal.id)
    assert result["outcome"] == "success"
    assert adapter.value == "new"
    assert len(adapter.calls) == 2


def test_revocation(host, adapter):
    proposal = approved(host)
    host.confirm(proposal.id, False)
    assert not host.execute("write", {"value": "new"}, proposal_id=proposal.id)["allow"]
    assert adapter.value == "initial"


def test_confirmation_bound_to_arguments(host, adapter):
    proposal = approved(host)
    assert not host.execute("write", {"value": "other"}, proposal_id=proposal.id)["allow"]
    adapter.value = "external change"
    assert not host.execute("write", {"value": "new"}, proposal_id=proposal.id)["allow"]


def test_resource_read_is_correlated(host):
    host.execute("read", {"resource": "other"})
    proposal = host.prepare("write", {"value": "new"})
    host.confirm(proposal.id, True)
    assert (
        "example.read_first"
        in host.execute("write", {"value": "new"}, proposal_id=proposal.id)["reasons"]
    )


def test_concurrent_same_approval_only_dispatches_once(host, adapter):
    # Keep the revision unchanged so only native approval consumption prevents reuse.
    proposal = approved(host, value="initial")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: host.execute("write", {"value": "initial"}, proposal_id=proposal.id),
                range(2),
            )
        )
    assert sum(result["allow"] for result in results) == 1
    denied = next(result for result in results if not result["allow"])
    assert denied["reasons"] == ["example.confirm"]
    assert [action for action, _ in adapter.calls].count("write") == 1


def test_uncertain_outcome_blocks_followups(host, adapter):
    proposal = approved(host)
    adapter.fail = True
    assert host.execute("write", {"value": "new"}, proposal_id=proposal.id)["outcome"] == "unknown"
    adapter.fail = False
    assert not host.execute("read", {})["allow"]


def test_duplicate_request_id_is_rejected(host, adapter):
    host.execute("read", {}, request_id="request-1")
    with pytest.raises(EngineError, match="duplicate"):
        host.execute("read", {}, request_id="request-1")
    assert len(adapter.calls) == 1
    assert host.execute("read", {})["allow"]


def test_engine_crash_is_fail_closed_and_recovers(host, adapter):
    host.engine.close()
    with pytest.raises(EngineError):
        host.execute("read", {})
    assert adapter.calls == []
    assert host.execute("read", {})["allow"]


def test_clock_rollback_rejected(host, adapter):
    host.execute("read", {})
    host.clock = lambda: 99
    with pytest.raises(EngineError, match="backwards"):
        host.execute("read", {})
    assert len(adapter.calls) == 1


def test_restart_replays_without_dispatch(tmp_path, adapter):
    path = tmp_path / "journal.sqlite"
    with GuardHost(
        "example", path, adapter, principal="alice", session="one", clock=lambda: 100
    ) as host:
        proposal = approved(host, value="initial")
        assert (
            host.execute("write", {"value": "initial"}, proposal_id=proposal.id)["outcome"]
            == "success"
        )
        version = host.engine.version
    with GuardHost(
        "example", path, adapter, principal="alice", session="one", clock=lambda: 100
    ) as host:
        assert host.engine.version == version
        assert len(adapter.calls) == 2
        denied = host.execute("write", {"value": "initial"}, proposal_id=proposal.id)
        assert not denied["allow"]
        assert denied["reasons"] == ["example.confirm"]


def test_second_writer_is_rejected(host, tmp_path, adapter):
    with pytest.raises(RuntimeError, match="writer"):
        GuardHost("example", tmp_path / "events.sqlite", adapter, principal="alice", session="two")


def test_symlink_cannot_bypass_journal_writer_lock(host, tmp_path, adapter):
    alias = tmp_path / "alias.sqlite"
    alias.symlink_to(host.database)
    with pytest.raises(RuntimeError, match="writer"):
        GuardHost("example", alias, adapter, principal="alice", session="one")


def test_failed_journal_initialization_releases_writer_lock(tmp_path, adapter):
    path = tmp_path / "journal.sqlite"
    path.write_bytes(b"not a SQLite database")
    # Retain the exception: garbage collection must not be needed to release resources.
    with pytest.raises(sqlite3.DatabaseError) as failure:
        GuardHost("example", path, adapter, principal="alice", session="one")
    path.unlink()
    with GuardHost("example", path, adapter, principal="alice", session="one") as host:
        assert host.execute("read", {})["allow"]
    assert failure.value is not None


def test_forged_observation_api_rejected(host):
    with pytest.raises(ValueError):
        host.observe_trusted("confirmed", "document")
    with pytest.raises(ValueError):
        host.observe_trusted("success", "document")


def test_native_pack_cannot_be_reloaded():
    with Engine("example") as engine, pytest.raises(EngineError, match="immutable"):
        engine.request({"op": "load", "domain": "retail"})


def test_malformed_or_missing_facts_deny(tmp_path):
    adapter = MemoryTools()
    with GuardHost(
        "retail", tmp_path / "events.sqlite", adapter, principal="alice", session="one"
    ) as host:
        result = host.execute("get_user_details", {"user_id": "alice"})
        assert not result["allow"] and result["errors"]
        assert adapter.calls == []


def test_journal_write_failure_prevents_dispatch(host, adapter):
    host.db.execute("""CREATE TEMP TRIGGER refuse_journal BEFORE INSERT ON journal
                    BEGIN SELECT RAISE(FAIL, 'injected journal failure'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        host.execute("read", {})
    assert adapter.calls == []
    assert host.engine.version == 0
    host.db.execute("DROP TRIGGER refuse_journal")
    assert host.execute("read", {})["outcome"] == "success"


def test_failed_recovery_keeps_subsequent_calls_disabled(host, adapter):
    host.execute("read", {})
    host.db.execute("UPDATE journal SET response='{}' WHERE seq=2")
    host.engine.close()
    for _ in range(2):
        with pytest.raises(EngineError, match="replay diverged"):
            host.execute("read", {})
        assert host.engine.process.poll() is not None
    assert len(adapter.calls) == 1


def test_rollback_failure_discards_uncommitted_engine_state(host, adapter, monkeypatch):
    db = host.db

    class BrokenJournal:
        def execute(self, sql, *args):
            if sql.startswith("INSERT INTO journal") or sql == "ROLLBACK":
                raise sqlite3.OperationalError("injected storage failure")
            return db.execute(sql, *args)

    with monkeypatch.context() as patch:
        patch.setattr(host, "db", BrokenJournal())
        with pytest.raises(sqlite3.OperationalError, match="injected"):
            host.execute("read", {})
        assert host.engine.process.poll() is not None
        assert adapter.calls == []
    db.execute("ROLLBACK")
    with pytest.raises(EngineError, match="unavailable"):
        host.execute("read", {})
    assert host.execute("read", {})["outcome"] == "success"


def test_close_waits_for_tool_outcome_before_releasing_writer(host, adapter, monkeypatch):
    entered, release, closing = Event(), Event(), Event()
    execute = adapter.execute

    def blocked_tool(action, arguments):
        entered.set()
        assert release.wait(5)
        return execute(action, arguments)

    def close():
        closing.set()
        host.close()

    monkeypatch.setattr(adapter, "execute", blocked_tool)
    with ThreadPoolExecutor(max_workers=2) as pool:
        execution = pool.submit(host.execute, "read", {})
        try:
            assert entered.wait(5)
            shutdown = pool.submit(close)
            assert closing.wait(5)
            with pytest.raises(TimeoutError):
                shutdown.result(timeout=0.1)
            with pytest.raises(RuntimeError, match="writer"):
                GuardHost("example", host.database, adapter, principal="alice", session="one")
        finally:
            release.set()
        assert execution.result(timeout=5)["outcome"] == "success"
        shutdown.result(timeout=5)
    with GuardHost("example", host.database, adapter, principal="alice", session="one") as reopened:
        assert reopened.events()[-1]["kind"] == "success"


def test_interrupted_engine_request_cannot_reuse_channel(monkeypatch):
    import os

    with Engine("example") as engine:
        read = os.read

        def interrupted_read(*args):
            read(*args)
            raise KeyboardInterrupt

        with monkeypatch.context() as patch:
            patch.setattr(os, "read", interrupted_read)
            with pytest.raises(KeyboardInterrupt):
                engine.request({"op": "load", "domain": "example"})
        assert engine.process.poll() is not None
        with pytest.raises(EngineError, match="unavailable"):
            engine.request({"op": "load", "domain": "example"})


def test_unknown_outcome_survives_conversation_change(tmp_path, adapter):
    path = tmp_path / "journal.sqlite"
    with GuardHost("example", path, adapter, principal="alice", session="one") as host:
        adapter.fail = True
        assert host.execute("read", {})["outcome"] == "unknown"
    adapter.fail = False
    with GuardHost("example", path, adapter, principal="alice", session="two") as host:
        assert not host.execute("read", {})["allow"]
        assert len(adapter.calls) == 1


def test_journal_corruption_and_wrong_identity_fail_closed(tmp_path, adapter):
    path = tmp_path / "journal.sqlite"
    with GuardHost("example", path, adapter, principal="alice", session="one") as host:
        host.execute("read", {})
        host.db.execute("UPDATE journal SET response='{}' WHERE seq=1")
    with pytest.raises(EngineError, match="replay diverged"):
        GuardHost("example", path, adapter, principal="alice", session="one")
    with pytest.raises(RuntimeError, match="identity"):
        GuardHost("example", path, adapter, principal="mallory", session="one")
    assert len(adapter.calls) == 1


def test_large_request_uses_complete_frame(host):
    payload = "x" * 200000
    assert host.execute("read", {"padding": payload})["outcome"] == "success"


def test_successful_outcome_is_auditable(host):
    host.execute("read", {})
    command = host.db.execute("SELECT command FROM journal ORDER BY seq DESC LIMIT 1").fetchone()[0]
    assert json.loads(command)["outcome"] == {"value": "initial"}
