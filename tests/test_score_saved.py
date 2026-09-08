import hashlib
import json
import sqlite3

import pytest

pytest.importorskip("tau2")

from leanguard.demo import MemoryTools
from leanguard.engine import default_binary
from leanguard.host import GuardHost
from leanguard.score_saved import expected_episodes, replay_journal, score_episode
from tau2.runner.helpers import get_tasks


def test_expected_episodes_includes_larger_domains_after_small_domain_exhausted():
    manifest = {
        "domains": ["retail", "airline"],
        "modes": ["baseline", "generic"],
        "task_ids": {"retail": ["0", "1"], "airline": ["a"]},
    }
    assert expected_episodes(manifest) == [
        ("retail", "baseline", "0"),
        ("retail", "generic", "0"),
        ("airline", "baseline", "a"),
        ("airline", "generic", "a"),
        ("retail", "baseline", "1"),
        ("retail", "generic", "1"),
    ]


@pytest.mark.parametrize(
    "error,termination",
    [
        ("RuntimeError: protocol retry budget exhausted", "agent_error"),
        ("ContextWindowExceededError: too long", "context_window_exceeded"),
        ("APIConnectionError: disconnected", "infrastructure_error"),
        ("APITimeoutError: too slow", "timeout"),
        ("ValueError: unexpected", "unexpected_error"),
    ],
)
def test_all_failed_episodes_receive_upstream_zero_even_if_state_diagnostic_passed(
    tmp_path, error, termination
):
    task = get_tasks("retail", task_split_name="base")[0]
    saved = {
        "domain": "retail",
        "mode": "baseline",
        "task_id": task.id,
        "error": error,
        "elapsed_seconds": 1,
        "seed": 300,
        "terminal_environment": {"all_met": True},
    }
    (tmp_path / "failure-state.json").write_text(json.dumps({"trajectory": []}))
    score = score_episode(tmp_path, saved, task, "unused_for_baseline")
    assert score["reward"] == score["local_combined_reward"] == 0
    assert score["upstream_reward_details"]["reward"] == 0
    assert score["termination"] == termination
    assert score["original_error"] == error
    assert score["terminal_environment_diagnostic"]["all_met"] is True


def test_native_replay_checks_response_and_fingerprint_without_redispatch(tmp_path):
    adapter = MemoryTools()
    with GuardHost(
        "example",
        tmp_path / "journal.sqlite",
        adapter,
        principal="alice",
        session="one",
        clock=lambda: 100,
    ) as host:
        assert host.execute("read", {})["allow"]
        assert not host.execute("write", {"value": "new"})["allow"]
    saved = {"domain": "example", "mode": "generic"}
    fingerprint = hashlib.sha256(default_binary().read_bytes()).hexdigest()
    result = replay_journal(tmp_path, saved, fingerprint)
    assert result["status"] == "all_responses_match_current_LeanGuard"
    assert result["decisions"] == 2
    assert len(adapter.calls) == 1
    with pytest.raises(ValueError, match="identity mismatch"):
        replay_journal(tmp_path, saved, "changed-binary")
    with sqlite3.connect(tmp_path / "journal.sqlite") as db:
        db.execute("UPDATE journal SET response='{}' WHERE seq=(SELECT MAX(seq) FROM journal)")
    with pytest.raises(ValueError, match="native replay mismatch"):
        replay_journal(tmp_path, saved, fingerprint)


def test_missing_journal_cannot_claim_verified(tmp_path):
    saved = {"domain": "retail", "mode": "generic"}
    with pytest.raises(ValueError, match="missing native journal"):
        replay_journal(tmp_path, saved, "unused")
    assert (
        replay_journal(tmp_path, {**saved, "error": "initialization failed"}, "unused")["status"]
        == "unavailable_after_episode_error"
    )
