"""Start an isolated Qwen3.5-4B vLLM server using this machine's cached artifacts."""

import argparse
import subprocess
from pathlib import Path

IMAGE = "vllm/vllm-openai@sha256:6fca82f415f2a3270aec7d70b84e0d1b5b0d0e6260c7fd15eb4478d48db06485"
REVISION = "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
NAME = "leanguard-qwen35-4b-v022"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("/home/debargha/.cache/huggingface/hub"))
    parser.add_argument("--port", type=int, default=18000)
    parser.add_argument("--name", default=NAME)
    parser.add_argument("--max-num-seqs", type=int, default=16)
    parser.add_argument("--prefix-caching", action="store_true")
    parser.add_argument("--print-command", action="store_true")
    args = parser.parse_args()
    snapshot = f"models--Qwen--Qwen3.5-4B/snapshots/{REVISION}"
    if not (args.cache / snapshot / "config.json").is_file():
        parser.error("the pinned base-model snapshot is missing")
    command = [
        "docker",
        "run",
        "-d",
        "--name",
        args.name,
        "--gpus",
        '"device=0"',
        "--shm-size",
        "2g",
        "-p",
        f"127.0.0.1:{args.port}:8000",
        "-v",
        f"{args.cache.resolve()}:/models:ro",
        IMAGE,
        f"/models/{snapshot}",
        "--served-model-name",
        "Qwen/Qwen3.5-4B",
        "--dtype",
        "bfloat16",
        "--max-model-len",
        "32768",
        "--gpu-memory-utilization",
        "0.20",
        "--max-num-seqs",
        str(args.max_num_seqs),
        "--reasoning-parser",
        "qwen3",
        "--enable-auto-tool-choice",
        "--tool-call-parser",
        "qwen3_coder",
        "--language-model-only",
        "--enforce-eager",
    ]
    if args.prefix_caching:
        command.append("--enable-prefix-caching")
    if args.print_command:
        import shlex

        print(shlex.join(command))
        return
    # Docker refuses a duplicate name, preserving an existing server and its logs.
    subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
