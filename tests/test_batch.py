from threading import Barrier

import pytest
from leanguard.batch import integration_error, run_batch


def test_failure_classification_excludes_policy_and_model_outcomes():
    assert integration_error({"error": "BadRequestError: bad chat template"}) == "BadRequestError"
    assert integration_error({"error": "AttributeError: broken recorder"}) == "AttributeError"
    assert integration_error({"error": "ValueError: scoring replay differs"}) == "replay_mismatch"
    assert integration_error({"error": "ExperimentHalted: stopped"}) is None
    assert integration_error({"error": "ValueError: protocol retry budget exhausted"}) is None
    assert integration_error({"guard": {"native_denials": 5}}) is None


def test_bounded_scheduler_halts_without_starting_remaining_jobs():
    started = Barrier(2)
    observations, halts = [], []

    def episode(index, stopped):
        started.wait(timeout=5)
        if index == 0:
            return {"error": "BadRequestError: invalid template"}
        assert stopped.wait(timeout=5)
        return {"error": "ExperimentHalted: stopped"}

    batch = run_batch(
        [(i,) for i in range(10)],
        episode,
        concurrency=2,
        max_errors=1,
        on_result=lambda result, results: observations.append(result),
        on_halt=halts.append,
    )
    assert len(observations) == 2
    assert batch.unstarted == 8
    assert halts == [batch.halted]
    assert batch.halted["categories"] == {"BadRequestError": 1}


def test_scheduler_completes_normal_jobs_and_preserves_unhandled_failure():
    halts = []
    batch = run_batch(
        [(i,) for i in range(5)],
        lambda i, stopped: {"index": i},
        concurrency=2,
        max_errors=1,
        on_result=lambda *args: None,
        on_halt=halts.append,
    )
    assert sorted(r["index"] for r in batch.results) == list(range(5))
    assert batch.unstarted == 0 and batch.halted is None

    def broken(stopped):
        raise RuntimeError("worker crashed")

    with pytest.raises(RuntimeError, match="worker crashed"):
        run_batch(
            [()],
            broken,
            concurrency=1,
            max_errors=1,
            on_result=lambda *args: None,
            on_halt=halts.append,
        )
    assert halts[0]["error"] == "RuntimeError: worker crashed"
