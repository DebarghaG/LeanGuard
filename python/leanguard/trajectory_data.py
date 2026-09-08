"""Read published rollout data as data; never execute embedded code or task verifiers."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from .engine import digest

DATASETS = {
    "snorkelai/Tau2-Bench-Verified-Airline-With-Code-Agents": "23e3afcdd9492e9e6cc240c124be07665a8d211b",
    "snorkelai/Tau2-Bench-Airline-With-Code-Agents": "81702cbf1e8161c8cfac732578898a73e23813fe",
    "fuvty/tau-bench-synthetic": "54ab66a42df9f1a62a8041b465b53925965dea02",
    "inclusionAI/AReaL-tau2-data": "86971dc03da6e7c1a7933295e05b84aab8215386",
}


def download_datasets(root):
    """Fetch immutable snapshots and hash every downloaded dataset file."""
    from huggingface_hub import HfApi, snapshot_download

    root.mkdir(parents=True, exist_ok=True)
    manifest = []
    api = HfApi()
    for repo, revision in DATASETS.items():
        directory = root / "datasets" / repo.replace("/", "--")
        snapshot_download(repo, repo_type="dataset", revision=revision, local_dir=directory)
        files = []
        for name in api.list_repo_files(repo, repo_type="dataset", revision=revision):
            path = directory / name
            with path.open("rb") as stream:
                checksum = hashlib.file_digest(stream, "sha256").hexdigest()
            files.append({"path": name, "bytes": path.stat().st_size, "sha256": checksum})
        manifest.append({"repo": repo, "revision": revision, "files": files})
    (root / "downloads.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


def messages(raw):
    """Normalize message envelopes without inferring actions from prose or reasoning."""
    result = []
    for index, original in enumerate(decoded(raw)):
        role = original["role"]
        if role == "system":
            continue
        calls = []
        for call in decoded(original.get("tool_calls") or []):
            function = call.get("function") or call
            arguments = decoded(function.get("arguments") or {})
            calls.append(
                {
                    "id": call.get("id"),
                    "name": function.get("name", ""),
                    "arguments": arguments,
                    "requestor": call.get("requestor", role),
                }
            )
        result.append(
            {
                "role": role,
                "content": original.get("content") or "",
                "calls": calls,
                "response_id": original.get("tool_call_id") or original.get("id"),
                "requestor": original.get("requestor"),
                "name": original.get("name"),
                "error": original.get("error"),
                "source_message": index,
            }
        )
    return result


def signature(message):
    """Compare content and actions across training prefixes with regenerated call IDs."""
    return digest(
        {
            "role": message["role"],
            "content": message["content"],
            "requestor": message["requestor"],
            "name": message["name"],
            "error": message["error"],
            "calls": [{k: v for k, v in call.items() if k != "id"} for call in message["calls"]],
        }
    )


def domain_for_dialog(dialog):
    if dialog.startswith("retail_dialog_"):
        return "retail"
    if dialog.startswith("airline_dialog_"):
        return "airline"
    if dialog.isdigit():
        return "telecom"
    raise ValueError(f"unrecognized dialogue domain: {dialog}")


def parquet_rows(path):
    import pyarrow.parquet as pq

    for batch in pq.ParquetFile(path).iter_batches(batch_size=64):
        yield from batch.to_pylist()


def normalize_datasets(root: Path):
    """Account for every row, retaining non-prefix branches instead of dropping them."""
    directory = root / "datasets"
    records = []
    coverage = {}
    for repo in [
        "snorkelai--Tau2-Bench-Airline-With-Code-Agents",
        "snorkelai--Tau2-Bench-Verified-Airline-With-Code-Agents",
    ]:
        path = directory / repo / "data/train-00000-of-00001.parquet"
        count = 0
        for index, row in enumerate(parquet_rows(path)):
            count += 1
            records.append(
                {
                    "id": f"{repo}/{index}",
                    "dataset": repo,
                    "domain": "airline",
                    "task_id": row["task_id"],
                    "model": row["model"],
                    "version": row["version"],
                    "reward": row["reward"],
                    "kind": "published_rollout",
                    "messages": messages(row["trace"]),
                    "source": {"file": str(path.relative_to(root)), "row": index},
                }
            )
        coverage[repo] = {"rollout_rows": count}

    repo = "fuvty--tau-bench-synthetic"
    path = directory / repo / "traj-GLM5/train-00000-of-00001.parquet"
    full = {}
    for index, row in enumerate(parquet_rows(path)):
        key = (row["domain"], str(row["task_id"]), row["trial"])
        record = {
            "id": f"{repo}/{row['domain']}/{row['task_id']}/{row['trial']}",
            "dataset": repo,
            "domain": row["domain"],
            "task_id": row["task_id"],
            "model": "GLM-5",
            "version": "traj-GLM5",
            "reward": row["reward"],
            "kind": "published_rollout",
            "messages": messages(row["messages"]),
            "termination": row["termination_reason"],
            "source": {"file": str(path.relative_to(root)), "row": index},
        }
        if key in full:
            raise ValueError(f"duplicate synthetic rollout key: {key}")
        full[key] = record
        records.append(record)
    full_signatures = {key: list(map(signature, r["messages"])) for key, r in full.items()}
    prefix_stats = Counter()
    path = directory / repo / "sft-GLM5/train-00000-of-00001.parquet"
    for index, row in enumerate(parquet_rows(path)):
        key = (row["domain"], str(row["task_id"]), row["trial"])
        normalized = messages(row["messages"])
        sig = list(map(signature, normalized))
        prefix_stats["training_rows"] += 1
        if key in full_signatures and sig == full_signatures[key][: len(sig)]:
            prefix_stats["training_prefixes_covered_by_full_rollouts"] += 1
        else:
            prefix_stats["additional_training_prefixes"] += 1
            records.append(
                {
                    "id": f"{repo}/sft/{index}",
                    "dataset": repo,
                    "domain": row["domain"],
                    "task_id": row["task_id"],
                    "model": "GLM-5",
                    "version": "sft-GLM5",
                    "reward": None,
                    "kind": "training_prefix",
                    "messages": normalized,
                    "source": {"file": str(path.relative_to(root)), "row": index},
                }
            )
    task_count = sum(
        1 for _ in parquet_rows(directory / repo / "tasks/train-00000-of-00001.parquet")
    )
    coverage[repo] = {"rollout_rows": len(full), "task_definition_rows": task_count, **prefix_stats}

    repo = "inclusionAI--AReaL-tau2-data"
    path = directory / repo / "tau2_sft_train.jsonl"
    candidates = {}
    stats = Counter()
    with path.open() as stream:
        for index, line in enumerate(stream):
            row = json.loads(line)
            metadata = row["metadata"]
            dialog = str(metadata["source_dialog_id"])
            normalized = messages(row["messages"] + [row["answer"]])
            sig = list(map(signature, normalized))
            stats["training_rows"] += 1
            domain = domain_for_dialog(dialog)
            stats[f"{domain}_training_rows"] += 1
            branches = candidates.setdefault(dialog, [])
            if any(sig == b[0][: len(sig)] for b in branches):
                continue
            # A later, longer prefix replaces the earlier prefix it contains.
            branches[:] = [b for b in branches if b[0] != sig[: len(b[0])]]
            branches.append(
                (
                    sig,
                    {
                        "id": f"{repo}/{dialog}/{index}",
                        "dataset": repo,
                        "domain": domain,
                        "task_id": metadata.get("task_id", dialog),
                        "model": "published_SFT",
                        "version": "sft",
                        "reward": metadata.get("reward"),
                        "kind": "maximal_training_prefix",
                        "messages": normalized,
                        "source": {
                            "file": str(path.relative_to(root)),
                            "row": index,
                            "dialog": dialog,
                            "turn": metadata["turn_index"],
                        },
                    },
                )
            )
    for branches in candidates.values():
        records.extend(record for _, record in branches)
    with (directory / repo / "tau2_rl_train.jsonl").open() as stream:
        tasks = sum(1 for line in stream if json.loads(line))
    coverage[repo] = {
        **stats,
        "dialogues": len(candidates),
        "maximal_prefixes": sum(map(len, candidates.values())),
        "dialogues_with_branches": sum(len(branches) > 1 for branches in candidates.values()),
        "task_definition_rows": tasks,
    }
    return records, coverage
