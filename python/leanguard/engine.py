from __future__ import annotations

import hashlib
import json
import os
import selectors
import subprocess
import threading
import time
from pathlib import Path


class EngineError(RuntimeError):
    pass


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def default_binary() -> Path:
    configured = os.environ.get("LEANGUARD_BINARY")
    if configured:
        return Path(configured).resolve()
    bundled = Path(__file__).resolve().parent / "bin" / "leanguard"
    if bundled.is_file():
        return bundled
    return Path(__file__).resolve().parents[2] / ".lake" / "build" / "bin" / "leanguard"


class Engine:
    """One serialized, bounded JSON channel to a compiled native Lean policy pack."""

    def __init__(self, domain: str, binary: Path | None = None, timeout: float = 10):
        self.binary = (binary or default_binary()).resolve()
        try:
            self.fingerprint = hashlib.sha256(self.binary.read_bytes()).hexdigest()
        except OSError as exc:
            raise EngineError(
                "Native executable unavailable; install a platform wheel, build with Lake, "
                "or supply binary= / LEANGUARD_BINARY."
            ) from exc
        self.timeout = timeout
        self._lock = threading.RLock()
        self._buffer = bytearray()
        self.process = subprocess.Popen(
            [str(self.binary)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            bufsize=0,
        )
        try:
            os.set_blocking(self.process.stdin.fileno(), False)
            response = self.request({"op": "load", "domain": domain})
            self.manifest = {**response["manifest"], "engine_sha256": self.fingerprint}
            self.version = response["version"]
        except BaseException:
            self.close()
            raise

    def request(self, command: dict) -> dict:
        with self._lock:
            if self.process.poll() is not None:
                raise EngineError("Lean engine is unavailable")
            encoded = (canonical({"protocol": 1, **command}) + "\n").encode()
            if len(encoded) > 8 * 1024 * 1024:
                raise EngineError("request exceeds 8 MiB")
            try:
                deadline = time.monotonic() + self.timeout
                with selectors.DefaultSelector() as selector:
                    selector.register(self.process.stdin, selectors.EVENT_WRITE)
                    offset = 0
                    while offset < len(encoded):
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 or not selector.select(remaining):
                            raise EngineError("Lean engine timed out receiving request")
                        try:
                            count = os.write(self.process.stdin.fileno(), encoded[offset:])
                        except BlockingIOError:
                            continue
                        if count == 0:
                            raise EngineError("Lean engine closed its input")
                        offset += count
                    selector.unregister(self.process.stdin)
                    selector.register(self.process.stdout, selectors.EVENT_READ)
                    while b"\n" not in self._buffer:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 or not selector.select(remaining):
                            raise EngineError("Lean engine timed out")
                        chunk = os.read(self.process.stdout.fileno(), 65536)
                        if not chunk:
                            raise EngineError("Lean engine closed its output")
                        self._buffer.extend(chunk)
                        if len(self._buffer) > 16 * 1024 * 1024:
                            raise EngineError("Lean response exceeds 16 MiB")
                line, _, rest = self._buffer.partition(b"\n")
                self._buffer = bytearray(rest)
                response = json.loads(line)
                if not isinstance(response, dict):
                    raise EngineError("invalid Lean response envelope")
                if response.get("ok") is not True:
                    raise EngineError(response.get("error", "invalid Lean response"))
                result = response["result"]
                if not isinstance(result, dict):
                    raise EngineError("invalid Lean result")
                if "version" in result:
                    if type(result["version"]) is not int or result["version"] < 0:
                        raise EngineError("invalid Lean version")
                    self.version = result["version"]
                return result
            except BaseException as exc:
                self.close()
                if isinstance(exc, (OSError, ValueError, KeyError, EngineError)):
                    raise EngineError(str(exc)) from exc
                raise

    def close(self):
        with self._lock:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            for stream in (self.process.stdin, self.process.stdout):
                if stream:
                    stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
