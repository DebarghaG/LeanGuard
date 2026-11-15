import pytest
from leanguard import GuardHost, MultiAgentHost
from leanguard.approval import ApprovalDesk
from leanguard.demo import MemoryTools


def answer(desk, proposal, accepted=True, **extra):
    with desk.lock:
        return desk.action(
            "/api/answer",
            {"proposal": proposal.id, "binding": proposal.binding, "accepted": accepted, **extra},
        )


def test_exact_consent_does_not_dispatch_and_is_consumed(tmp_path):
    adapter = MemoryTools()
    with GuardHost(
        "example", tmp_path / "journal", adapter, principal="alice", session="one"
    ) as host:
        desk = ApprovalDesk(host)
        proposal = host.prepare(
            "write", {"value": "<script>spoof</script>", "reference": 9007199254740993}
        )
        desk.enqueue(proposal.id)
        assert "9007199254740993" in desk.state()["proposals"][0]["details_text"]
        with pytest.raises(ValueError, match="displayed"):
            answer(desk, proposal, binding="changed")
        with pytest.raises(TypeError, match="Boolean"):
            answer(desk, proposal, accepted="yes")
        state = answer(desk, proposal)
        assert state["proposals"][0]["status"] == "accepted"
        assert adapter.calls == []
        with pytest.raises(ValueError, match="already"):
            answer(desk, proposal)
        assert not host.execute("write", {"value": "different"}, proposal_id=proposal.id)["allow"]
        assert not host.execute(
            "write",
            {"value": "<script>spoof</script>", "reference": 9007199254740993},
            proposal_id=proposal.id,
        )["allow"]  # approval cannot override missing read
        host.execute("read", {})
        assert host.execute(
            "write",
            {"value": "<script>spoof</script>", "reference": 9007199254740993},
            proposal_id=proposal.id,
        )["allow"]
        assert desk.state()["proposals"][0]["status"] == "consumed"
        assert desk.state()["proposals"][0]["outcome"] == "success"
        with pytest.raises(ValueError, match="already"):
            answer(desk, proposal)


def test_rejection_revocation_stale_revision_and_queue_authority(tmp_path):
    adapter = MemoryTools()
    with GuardHost(
        "example", tmp_path / "journal", adapter, principal="alice", session="one"
    ) as host:
        desk = ApprovalDesk(host)
        proposal = host.prepare("write", {"value": "approved"})
        with pytest.raises(ValueError, match="queue"):
            answer(desk, proposal)
        desk.enqueue(proposal.id)
        answer(desk, proposal)
        assert answer(desk, proposal, False)["proposals"][0]["status"] == "rejected"
        with pytest.raises(ValueError, match="already"):
            answer(desk, proposal)
        new = host.prepare("write", {"value": "stale"})
        desk.enqueue(new.id)
        adapter.value = "changed externally"
        with pytest.raises(ValueError, match="state changed"):
            answer(desk, new)
        with pytest.raises(ValueError, match="Only"):
            desk.action("/api/enqueue", {"proposal": new.id})
        assert adapter.calls == []
    with (
        GuardHost(
            "example", tmp_path / "journal", adapter, principal="alice", session="other"
        ) as other,
        pytest.raises(ValueError, match="another conversation"),
    ):
        ApprovalDesk(other).enqueue(proposal.id)


def test_delegated_consent_remains_bound_to_actor(tmp_path):
    with MultiAgentHost(
        "multiagent.example",
        tmp_path / "journal",
        MemoryTools(),
        principal="alice",
        session="one",
        clock=lambda: 100,
    ) as host:
        actor = host.grant(
            "planner",
            workflow="workflow",
            actions=["read", "write"],
            resources=["document"],
            calls=10,
            amount=100,
            expires=1000,
        )
        other = actor.delegate(
            "worker",
            actions=["read", "write"],
            resources=["document"],
            peers=[""],
            calls=5,
            amount=50,
            expires=1000,
        )
        actor.execute("read", {})
        proposal = actor.prepare("write", {"value": "bound"})
        desk = ApprovalDesk(host)
        desk.enqueue(proposal.id)
        assert '"actor": "planner"' in desk.state()["proposals"][0]["details_text"]
        answer(desk, proposal)
        assert not other.execute("write", {"value": "bound"}, proposal_id=proposal.id)["allow"]
        assert actor.execute("write", {"value": "bound"}, proposal_id=proposal.id)["allow"]


def test_unknown_outcome_is_visible_and_not_reapproved(tmp_path):
    class Uncertain(MemoryTools):
        def execute(self, action, arguments):
            result = super().execute(action, arguments)
            if action == "write":
                raise RuntimeError("lost receipt after mutation")
            return result

    with GuardHost(
        "example", tmp_path / "journal", Uncertain(), principal="alice", session="one"
    ) as host:
        host.execute("read", {})
        proposal = host.prepare("write", {"value": "uncertain"})
        desk = ApprovalDesk(host)
        desk.enqueue(proposal.id)
        answer(desk, proposal)
        assert (
            host.execute("write", {"value": "uncertain"}, proposal_id=proposal.id)["outcome"]
            == "unknown"
        )
        state = desk.state()["proposals"][0]
        assert (state["status"], state["outcome"]) == ("consumed", "unknown")
        with pytest.raises(ValueError, match="already"):
            answer(desk, proposal)
