"""Score all saved benchmark attempts and replay native journals without tool dispatch."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from leanguard.engine import Engine, canonical, default_binary, digest

from .benchmark import ROOT, executed_trajectory, write_json


def expected_episodes(manifest):
    """Preserve the runner's interleaved order, including unequal domain sizes."""
    task_ids = manifest["task_ids"]
    return [
        (domain, mode, task_ids[domain][index])
        for index in range(max(map(len, task_ids.values()), default=0))
        for domain in manifest["domains"]
        if index < len(task_ids[domain])
        for mode in manifest["modes"]
    ]


def failure_reason(error):
    from tau2.data_model.simulation import TerminationReason

    if "protocol retry budget exhausted" in error:
        return TerminationReason.AGENT_ERROR
    if error.startswith("ContextWindowExceededError:"):
        return TerminationReason.CONTEXT_WINDOW_EXCEEDED
    if error.startswith(("TimeoutError:", "APITimeoutError:")):
        return TerminationReason.TIMEOUT
    if error.startswith(
        (
            "APIConnectionError:",
            "ServiceUnavailableError:",
            "InternalServerError:",
            "ExperimentHalted:",
        )
    ):
        return TerminationReason.INFRASTRUCTURE_ERROR
    return TerminationReason.UNEXPECTED_ERROR


def replay_journal(directory, saved, binary_sha):
    if saved["mode"] == "baseline":
        return {"status": "baseline_unenforced", "commands": 0, "decisions": 0}
    journal = directory / "journal.sqlite"
    if not journal.exists():
        if saved.get("error"):
            return {"status": "unavailable_after_episode_error", "commands": 0, "decisions": 0}
        raise ValueError(f"missing native journal: {directory}")
    with sqlite3.connect(journal.resolve().as_uri() + "?mode=ro", uri=True) as db:
        metadata = dict(db.execute("SELECT key, value FROM metadata"))
        if metadata.get("engine") != binary_sha or metadata.get("domain") != saved["domain"]:
            raise ValueError(f"native journal identity mismatch: {directory}")
        rows = list(db.execute("SELECT seq, command, response FROM journal ORDER BY seq"))
    decisions = 0
    with Engine(saved["domain"]) as engine:
        if engine.fingerprint != binary_sha:
            raise ValueError("compiled policy changed during replay")
        for seq, command_json, expected in rows:
            command = json.loads(command_json)
            if canonical(engine.request(command)) != canonical(json.loads(expected)):
                raise ValueError(f"native replay mismatch: {directory}, command {seq}")
            decisions += command["op"] == "admit"
    return {
        "status": "all_responses_match_current_LeanGuard",
        "commands": len(rows),
        "decisions": decisions,
    }


def score_episode(directory, saved, task, binary_sha):
    from tau2.data_model.simulation import SimulationRun
    from tau2.data_model.tasks import RewardType
    from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation

    native = replay_journal(directory, saved, binary_sha)
    task = task.model_copy(deep=True)
    task.evaluation_criteria.reward_basis = [
        b for b in task.evaluation_criteria.reward_basis if b != RewardType.NL_ASSERTION
    ]
    trajectory = directory / "trajectory.json"
    if trajectory.exists():
        simulation = SimulationRun.model_validate_json(trajectory.read_text())
        source = "saved_trajectory"
    else:
        if not saved.get("error"):
            raise ValueError(f"missing trajectory without an episode error: {directory}")
        failure_path = directory / "failure-state.json"
        failure = json.loads(failure_path.read_text()) if failure_path.exists() else {}
        simulation = SimulationRun(
            id=directory.name,
            task_id=saved["task_id"],
            start_time="unrecorded; see original model logs",
            end_time="unrecorded; see original model logs",
            duration=saved["elapsed_seconds"],
            termination_reason=failure_reason(saved["error"]),
            messages=failure.get("trajectory", []),
            seed=saved["seed"],
            info={"reconstructed_for_scoring": True, "original_error": saved["error"]},
        )
        source = "premature_termination_zero_from_upstream_evaluator"
    if simulation.task_id != saved["task_id"]:
        raise ValueError(f"trajectory task mismatch: {directory}")
    calls = directory / "guard-calls.json"
    blocked = (
        {c["id"] for c in json.loads(calls.read_text()) if not c["dispatched"]}
        if calls.exists()
        else set()
    )
    simulation.messages = executed_trajectory(simulation.messages or [], blocked)
    reward = evaluate_simulation(
        simulation,
        task,
        EvaluationType.ALL,
        solo_mode=False,
        domain=saved["domain"],
        strict_replay=True,
    )
    original_score = saved.get("score")
    if original_score is not None and reward.reward != original_score["deterministic"]["reward"]:
        raise ValueError(f"saved and replayed task scores disagree: {directory}")
    # A completed conversation with a failed live-state check is not a valid success.
    # Keep its upstream replay diagnostic separate from the all-attempts result.
    score_error = saved.get("error") if trajectory.exists() and original_score is None else None
    attempted_reward = 0.0 if score_error else reward.reward
    local_combined = (original_score or {}).get("local_combined_reward")
    if attempted_reward == 0:
        local_combined = 0.0
    return {
        "domain": saved["domain"],
        "mode": saved["mode"],
        "task_id": saved["task_id"],
        "reward": attempted_reward,
        "local_combined_reward": local_combined,
        "scoring_source": "invalid_live_scoring_zero" if score_error else source,
        "termination": simulation.termination_reason.value,
        "original_error": saved.get("error"),
        "native_replay": native,
        "upstream_reward_details": reward.model_dump(mode="json"),
        "original_live_state_match": (original_score or {}).get("replay_matches_live_state"),
        "terminal_environment_diagnostic": saved.get("terminal_environment"),
    }


def score_directory(run):
    from tau2.runner.helpers import get_tasks

    manifest = json.loads((run / "manifest.json").read_text())
    original = json.loads((run / "report.json").read_text())
    binary_sha = hashlib.sha256(default_binary().read_bytes()).hexdigest()
    if binary_sha != manifest["policy_binary_sha256"]:
        raise ValueError("compiled policy differs from the saved run")
    revision = subprocess.check_output(
        ["git", "-C", str(ROOT / ".tau2"), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != manifest["tau_revision"]:
        raise ValueError("benchmark revision mismatch")
    tasks = {
        d: {t.id: t for t in get_tasks(d, task_split_name="base")} for d in manifest["domains"]
    }
    expected = expected_episodes(manifest)
    if len(set(expected)) != len(expected):
        raise ValueError("duplicate episodes in manifest")
    if (
        digest([tasks[d][task_id].model_dump(mode="json") for d, _, task_id in expected])
        != manifest["task_digest"]
    ):
        raise ValueError("recorded task contents changed")
    recorded = {(r["domain"], r["mode"], r["task_id"]): r for r in original["results"]}
    if len(recorded) != len(original["results"]):
        raise ValueError("duplicate episodes in original report")
    if set(recorded) - set(expected):
        raise ValueError("report contains episodes outside the manifest")
    if len(expected) - len(recorded) != original["unstarted_episodes"]:
        raise ValueError("report does not account for every planned episode")
    paths = {}
    for path in sorted(run.glob("*/*/*/result.json")):
        saved = json.loads(path.read_text())
        key = (saved["domain"], saved["mode"], saved["task_id"])
        if key in paths or saved != recorded.get(key):
            raise ValueError(f"episode artifact disagrees with report: {path}")
        paths[key] = path
    if set(paths) != set(recorded):
        raise ValueError("missing episode artifacts")
    results = []
    for key in expected:
        if key not in paths:
            continue
        path = paths[key]
        row = score_episode(path.parent, recorded[key], tasks[key[0]][key[2]], binary_sha)
        row.update(
            source_result=str(path.relative_to(run)),
            source_result_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        results.append(row)
    by_mode = {}
    for mode in manifest["modes"]:
        group = [r for r in results if r["mode"] == mode]
        by_mode[mode] = {
            "episodes": len(group),
            "reward_sum": sum(r["reward"] for r in group),
            "mean_reward": sum(r["reward"] for r in group) / len(group) if group else None,
            "local_combined_scored": sum(r["local_combined_reward"] is not None for r in group),
            "local_combined_successes": sum(r["local_combined_reward"] == 1 for r in group),
        }
    return {
        "scored_at_utc": datetime.now(UTC).isoformat(),
        "run": str(run),
        "tau_revision": revision,
        "current_LeanGuard_binary_sha256": binary_sha,
        "upstream_evaluator": "tau2.evaluator.evaluator.evaluate_simulation / ALL / strict_replay=True",
        "score_scope": "deterministic task reward; NL assertions excluded as in the original experiment",
        "failure_rule": "premature termination receives reward 0; live scoring errors receive conservative all-attempts zero; final-state diagnostics do not override scores",
        "planned_episodes": len(expected),
        "episodes": len(results),
        "unstarted_episodes": original["unstarted_episodes"],
        "halted": original["halted"],
        "reward_sum": sum(r["reward"] for r in results),
        "mean_reward": sum(r["reward"] for r in results) / len(results) if results else None,
        "by_mode": by_mode,
        "native_commands_replayed": sum(r["native_replay"]["commands"] for r in results),
        "native_decisions_replayed": sum(r["native_replay"]["decisions"] for r in results),
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.run / "all-episode-scores"
    if output.exists():
        raise FileExistsError("choose a new score directory; previous artifacts are preserved")
    report = score_directory(args.run)
    write_json(output / "scores.json", report)
    columns = [
        "domain",
        "mode",
        "task_id",
        "reward",
        "local_combined_reward",
        "termination",
        "scoring_source",
    ]
    with (output / "scores.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report["results"])
    (output / "score_saved.py").write_text(Path(__file__).read_text())
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2))
    return int(bool(report["unstarted_episodes"] or report["halted"]))


if __name__ == "__main__":
    raise SystemExit(main())
