from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from leanguard import Engine, EngineError, MultiAgentHost, replay
from leanguard.demo import MemoryTools


@pytest.fixture
def host(tmp_path):
    with MultiAgentHost(
        "multiagent.example",
        tmp_path / "agents.sqlite",
        MemoryTools(),
        principal="tenant/alice",
        session="conversation",
        clock=lambda: 100,
    ) as host:
        yield host


def grant(host, **changes):
    return host.grant(
        **{
            "actor": "planner",
            "workflow": "workflow-1",
            "actions": ["read", "write"],
            "resources": ["document"],
            "calls": 10,
            "amount": 100,
            "expires": 1000,
            **changes,
        }
    )


def child(parent, actor="worker", **changes):
    return parent.delegate(
        actor,
        **{
            "actions": ["read"],
            "resources": ["document"],
            "peers": [""],
            "calls": 10,
            "amount": 100,
            "expires": 1000,
            **changes,
        },
    )


def test_required_authority_and_original_policy_both_apply(host):
    agent = grant(host)
    assert not host.execute("read", {})["allow"]
    assert agent.execute("read", {})["outcome"] == "success"
    denied = agent.execute("write", {"value": "changed"})
    assert not denied["allow"]
    assert "example.confirm" in denied["reasons"]
    assert len(host.adapter.calls) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"actor": "mallory"},
        {"workflow": "other"},
        {"delegation": "invented"},
    ],
)
def test_bound_identity_cannot_be_changed(host, changes):
    agent = replace(grant(host), **changes)
    assert not agent.execute("read", {})["allow"]
    assert host.adapter.calls == []


@pytest.mark.parametrize(
    "changes",
    [
        {"actions": ["write"]},
        {"resources": ["other"]},
        {"peers": ["unapproved"]},
        {"calls": 11},
        {"amount": 101},
        {"expires": 1001},
        {"depth": 4},
    ],
)
def test_child_cannot_expand_authority(host, changes):
    parent = grant(host, actions=["read"])
    with pytest.raises(EngineError, match="escalation"):
        child(parent, **changes)
    assert parent.execute("read", {})["allow"]


def test_parallel_children_share_ancestor_budget(host):
    parent = grant(host)
    agents = [child(parent, actor=name) for name in ("worker-a", "worker-b")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda a: a.execute("read", {"amount": 60}), agents))
    assert sum(r["allow"] for r in results) == 1
    assert len(host.adapter.calls) == 1
    assert not parent.execute("read", {"amount": 41})["allow"]
    assert parent.execute("read", {"amount": 40})["allow"]


def test_revocation_and_expiry_reach_descendants(host):
    parent = grant(host)
    agent = child(parent)
    assert agent.execute("read", {})["allow"]
    host.revoke(parent.delegation)
    assert not agent.execute("read", {})["allow"]
    other = grant(host, actor="other", workflow="other", expires=100)
    assert other.execute("read", {})["allow"]  # inclusive deadline
    host.clock = lambda: 101
    assert not other.execute("read", {})["allow"]


def test_approvals_are_bound_to_actor_and_delegation(host):
    first = grant(host)
    second = child(first, actor="other", actions=["read", "write"])
    assert first.execute("read", {})["allow"]
    proposal = first.prepare("write", {"value": "initial"})
    host.confirm(proposal.id, True)
    assert not second.execute("write", {"value": "initial"}, proposal_id=proposal.id)["allow"]
    assert first.execute("write", {"value": "initial"}, proposal_id=proposal.id)["allow"]
    assert not first.execute("write", {"value": "initial"}, proposal_id=proposal.id)["allow"]


def test_recovery_preserves_grants_budgets_and_revocations(host):
    first = grant(host, calls=1)
    second = child(grant(host, actor="parent", workflow="other"))
    assert first.execute("read", {})["allow"]
    host.revoke(second.delegation)
    path, adapter = host.database, host.adapter
    host.close()
    with MultiAgentHost(
        "multiagent.example",
        path,
        adapter,
        principal="tenant/alice",
        session="conversation",
        clock=lambda: 100,
    ) as reopened:
        assert not reopened.bind(first.delegation).execute("read", {})["allow"]
        assert not reopened.bind(second.delegation).execute("read", {})["allow"]
        assert len(adapter.calls) == 1


def test_trace_audits_do_not_misrepresent_missing_authority_as_allowed(host):
    assert grant(host).execute("read", {})["allow"]
    with Engine("multiagent.example") as engine:
        rows = list(replay(engine, host.events()))
    assert rows[-1]["assessment"] == "insufficient_evidence"
    assert "journal replay" in rows[-1]["decision"]["errors"][0]


def test_workflow_interleaving_does_not_remove_grant_witness(host):
    first = child(grant(host))
    second = grant(host, actor="foreign", workflow="other")
    host.revoke(second.delegation)
    assert first.execute("read", {})["allow"]


def test_new_root_cannot_reset_a_workflow_budget(host):
    grant(host)
    with pytest.raises(EngineError, match="already has an authority root"):
        grant(host, actor="second-root")
