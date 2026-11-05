"""LeanGuard adapter for the PBS tools used by the ALCF pbsMCP example.

The adapter runs no scheduler command itself. It is given two callables: one
that runs a tool (over MCP or in process) and one that lists the user's jobs.
Everything the policy reads comes from `snapshot`, so the facts can be tested
without a scheduler.
"""

from __future__ import annotations

import hashlib
import math
import re
import threading
from pathlib import Path

from leanguard import ReadOnlyToolError, Snapshot

SUBMITS = frozenset({"submit_job"})
SCRIPT_WRITERS = frozenset(
    {"generate_sim_script", "generate_aurora_pytorch_script", "generate_aurora_mpi_script"}
)
JOB_CONTROLS = frozenset({"delete_job", "hold_job", "release_job"})
QUEUE_READS = frozenset({"list_jobs", "get_job_status", "get_job_summary"})
OTHER_READS = frozenset({"list_queues", "list_nodes"})
FILE_READS = frozenset({"read_local_file"})
MUTATING = SUBMITS | SCRIPT_WRITERS | JOB_CONTROLS
READS = QUEUE_READS | OTHER_READS | FILE_READS
TOOLS = MUTATING | READS

# PBS defaults that the PBS MCP server applies when the agent leaves a field out.
SUBMIT_DEFAULTS = {"queue": "debug", "node_count": 1, "walltime": "00:10:00"}
FINISHED_STATES = frozenset({"F", "X"})

# Lines that put a credential into a job script. Heuristic, by design.
SECRET_PATTERNS = [
    re.compile(r"(?i)\b(export\s+)?[A-Z0-9_]*(API_KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*\s*=\s*\S"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]{16,}"),
    re.compile(r"\bAg[A-Za-z0-9]{40,}\b"),  # Globus access token prefix
]

# Paths an agent must never read. Checked against the resolved path.
CREDENTIAL_DIRS = (".globus", ".ssh", ".aws", ".config/gcloud")
CREDENTIAL_NAMES = frozenset({"tokens.json", ".netrc", "id_rsa", "id_ed25519", "credentials"})
CREDENTIAL_SUFFIXES = frozenset({".pem", ".key"})


def walltime_minutes(walltime: str) -> int:
    """Whole minutes in a PBS walltime, rounded up. Accepts HH:MM:SS, MM:SS or seconds."""
    parts = str(walltime).strip().split(":")
    if not all(part.isdigit() for part in parts) or len(parts) > 3:
        raise ValueError(f"not a PBS walltime: {walltime!r}")
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return math.ceil(seconds / 60)


def submit_arguments(arguments: dict) -> dict:
    """The submit as PBS will see it, with the server's defaults filled in."""
    normalized = {**SUBMIT_DEFAULTS, **arguments}
    normalized["node_count"] = int(normalized["node_count"])
    normalized["queue"] = str(normalized["queue"] or SUBMIT_DEFAULTS["queue"])
    normalized["walltime"] = str(normalized["walltime"] or SUBMIT_DEFAULTS["walltime"])
    return normalized


def node_minutes(arguments: dict) -> int:
    """node_count × walltime, in whole minutes. This is the event amount."""
    normalized = submit_arguments(arguments)
    if normalized["node_count"] <= 0:
        raise ValueError("node_count must be positive")
    return normalized["node_count"] * walltime_minutes(normalized["walltime"])


def normalize_path(raw: str) -> Path:
    """The path `read_local_file` will actually open.

    The tool strips everything up to the first colon, then expands `~`. Repeat
    that here and resolve symlinks, so the policy judges the real file.
    """
    value = raw.split(":", 1)[1] if ":" in raw else raw
    return Path(value).expanduser().resolve()


def is_credential_path(path: Path, home: Path) -> bool:
    resolved = path.resolve()
    home = home.resolve()
    try:
        relative = resolved.relative_to(home)
    except ValueError:
        relative = None
    if relative is not None and relative.parts:
        first = relative.parts[0]
        if first in CREDENTIAL_DIRS or "/".join(relative.parts[:2]) in CREDENTIAL_DIRS:
            return True
    return resolved.name in CREDENTIAL_NAMES or resolved.suffix in CREDENTIAL_SUFFIXES


def has_secret(text: str) -> bool:
    return any(pattern.search(line) for line in text.splitlines() for pattern in SECRET_PATTERNS)


def _digest(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


class PBSAdapter:
    """Adapter contract from `leanguard.host`: `snapshot`, `execute`, `lock`.

    `call_tool(name, arguments)` runs the real tool and returns its JSON result.
    `qstat()` returns the user's jobs as dicts with `job_id`, `state`, `queue`.
    `read_file(path)` reads a submit script; it exists so tests can fake it.
    """

    def __init__(
        self,
        *,
        call_tool,
        qstat,
        read_file=None,
        home: Path | None = None,
        server: str = "pbs",
        schemas: dict | None = None,
    ):
        self.call_tool, self.qstat = call_tool, qstat
        self.read_file = read_file or (lambda path: Path(path).read_text(errors="replace"))
        self.home = Path(home) if home is not None else Path.home()
        self.resource = f"pbs:{server}"
        self.schemas = schemas or {}
        self.lock = threading.RLock()

    # -- contract -------------------------------------------------------

    def snapshot(self, action, arguments, customer):
        if action in SUBMITS:
            return self._submit_snapshot(arguments)
        if action in FILE_READS:
            path = normalize_path(str(arguments.get("path", "")))
            return Snapshot(
                resource=f"file:{path}",
                revision=_digest(str(path)),
                facts={"path_is_credential": is_credential_path(path, self.home)},
                arguments={**arguments, "path": str(path)},
            )
        if action in JOB_CONTROLS:
            jobs = self._active_jobs()
            target = [j for j in jobs if j.get("job_id") == arguments.get("job_id")]
            return Snapshot(
                resource=self.resource,
                revision=_digest(*(f"{j['job_id']}={j.get('state')}" for j in target)),
                facts={},
                arguments=dict(arguments),
            )
        if action in TOOLS:
            return Snapshot(
                resource=self.resource, revision="", facts={}, arguments=dict(arguments)
            )
        raise ValueError(f"unknown tool {action!r}")

    def execute(self, action, arguments):
        result = self.call_tool(action, arguments)
        if action in READS and isinstance(result, dict) and result.get("success") is False:
            # A failed read changed nothing, and must not count as an observation.
            raise ReadOnlyToolError(str(result.get("error", "read failed")))
        return result

    def mutating(self, action):
        return action in MUTATING

    def tool_schemas(self):
        return self.schemas

    # -- facts ----------------------------------------------------------

    def _active_jobs(self):
        return [j for j in self.qstat() if str(j.get("state", "")).upper() not in FINISHED_STATES]

    def _submit_snapshot(self, arguments):
        normalized = submit_arguments(arguments)
        jobs = self._active_jobs()
        debug_jobs = [j for j in jobs if j.get("queue") == "debug"]
        script = Path(str(normalized["script_path"])).expanduser()
        try:
            text = self.read_file(script)
        except OSError:
            text, exists = "", False
        else:
            exists = True
        script_digest = _digest(text) if exists else ""
        minutes = node_minutes(normalized)
        facts = {
            "debug_jobs_active": len(debug_jobs),
            "node_minutes": minutes,
            "script_exists": exists,
            "script_digest": script_digest,
            "script_secret_pattern": has_secret(text),
        }
        # Only what the rules depend on: the user's own unfinished jobs and the script.
        # Other users' activity must not stale an approval.
        revision = _digest(
            *sorted(f"{j.get('job_id')}={j.get('state')}" for j in jobs), script_digest
        )
        return Snapshot(
            resource=self.resource,
            revision=revision,
            facts=facts,
            arguments=normalized,
            amount=minutes,
            units={"amount": "node-minutes"},
        )
