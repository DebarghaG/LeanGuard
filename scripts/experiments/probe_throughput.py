"""Fixed-token local serving microbenchmark, not a task-quality evaluation."""

import argparse
import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from scripts.experiments.benchmark import local_endpoint, write_json


def probe(endpoint, concurrency, requests, tokens):
    payload = {
        "model": "Qwen/Qwen3.5-4B",
        "messages": [
            {"role": "system", "content": "Answer the user's request accurately. " * 300},
            {"role": "user", "content": "List integers from 1 to 1000, separated by commas."},
        ],
        "temperature": 0.7,
        "max_tokens": tokens,
        "ignore_eos": True,
        "chat_template_kwargs": {"enable_thinking": False},
    }

    def request(index):
        start = time.monotonic()
        response = httpx.post(
            endpoint + "/chat/completions", json={**payload, "seed": index}, timeout=180
        )
        response.raise_for_status()
        body = response.json()
        return {"seconds": time.monotonic() - start, "tokens": body["usage"]["completion_tokens"]}

    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        rows = list(pool.map(request, range(requests)))
    elapsed = time.monotonic() - start
    return {
        "concurrency": concurrency,
        "requests": requests,
        "seconds": elapsed,
        "output_tokens": sum(r["tokens"] for r in rows),
        "output_tokens_per_second": sum(r["tokens"] for r in rows) / elapsed,
        "median_request_seconds": statistics.median(r["seconds"] for r in rows),
        "max_request_seconds": max(r["seconds"] for r in rows),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:18000/v1")
    parser.add_argument("--concurrency", nargs="+", type=int, default=[4, 8, 12, 16])
    parser.add_argument("--requests", type=int, default=24)
    parser.add_argument("--tokens", type=int, default=128)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    endpoint = local_endpoint(args.endpoint)
    if args.output.exists():
        raise FileExistsError(args.output)
    rows = []
    for concurrency in args.concurrency:
        row = probe(endpoint, concurrency, args.requests, args.tokens)
        rows.append(row)
        print(json.dumps(row), flush=True)
    write_json(
        args.output,
        {"kind": "fixed_token_serving_microbenchmark", "options": vars(args), "results": rows},
    )


if __name__ == "__main__":
    main()
