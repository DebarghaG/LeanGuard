"""Bounded episode scheduling and cooperative failure containment."""

from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from threading import Event


class ExperimentHalted(RuntimeError):
    """The batch stopped before the next generation or tool dispatch."""


@dataclass
class BatchResult:
    results: list[dict]
    halted: dict | None
    unstarted: int


def integration_error(result: dict) -> str | None:
    """Operational stop signal, not a label for policy-violation research."""
    error = result.get("error", "")
    if not error or error.startswith("ExperimentHalted:"):
        return None
    if "protocol retry budget exhausted" in error:
        return None
    category = error.split(":", 1)[0]
    if category in {
        "BadRequestError",
        "AuthenticationError",
        "PermissionDeniedError",
        "NotFoundError",
        "ServiceUnavailableError",
        "APIConnectionError",
        "InternalServerError",
        "AttributeError",
        "TypeError",
        "NameError",
        "ImportError",
        "ModuleNotFoundError",
    }:
        return category
    if "scoring replay differs" in error:
        return "replay_mismatch"
    if result.get("guard", {}).get("adapter_errors", 0):
        return "adapter_error"
    return None


def run_batch(jobs, worker, *, concurrency, max_errors, on_result, on_halt) -> BatchResult:
    """Keep at most `concurrency` jobs submitted; never refill a halted batch.

    Workers receive a shared Event as their final argument and must check it at
    generation/dispatch boundaries. Callbacks run only in the coordinating thread.
    """
    if concurrency < 1 or max_errors < 1:
        raise ValueError("concurrency and error limit must be positive")
    remaining = iter(jobs)
    stopped = Event()
    errors = Counter()
    results = []
    halted = None
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        pending = set()

        def fill():
            while not stopped.is_set() and len(pending) < concurrency:
                job = next(remaining, None)
                if job is None:
                    break
                pending.add(pool.submit(worker, *job, stopped))

        try:
            fill()
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    result = future.result()
                    results.append(result)
                    category = integration_error(result)
                    if category:
                        errors[category] += 1
                    if sum(errors.values()) >= max_errors and halted is None:
                        stopped.set()
                        halted = {
                            "reason": "repeated integration errors",
                            "categories": dict(errors),
                            "finished_at_halt": len(results),
                        }
                        on_halt(halted)
                    on_result(result, results)
                fill()
        except BaseException as exc:
            stopped.set()
            if halted is None:
                on_halt({"reason": "batch interrupted", "error": f"{type(exc).__name__}: {exc}"})
            raise
    return BatchResult(results, halted, len(jobs) - len(results))
