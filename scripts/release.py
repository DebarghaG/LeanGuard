"""Build verified local release candidates; never publish or alter Git history."""

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*command, capture=False, **kwargs):
    return subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        **kwargs,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--allow-dirty", action="store_true", help="Local candidates only")
    args = parser.parse_args()
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+rc\d+", version):
        parser.error("only release-candidate versions are supported during dogfooding")
    dirty = bool(run("git", "status", "--porcelain", capture=True).stdout)
    if dirty and not args.allow_dirty:
        parser.error("commit reviewed changes first, or use --allow-dirty for a local candidate")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    run(sys.executable, "scripts/verify.py")
    audit = run("lake", "env", "lean", "Audit.lean", capture=True).stdout
    binary = ROOT / ".lake/build/bin/leanguard"
    metadata = {
        "format": 1,
        "version": version,
        "channel": "release-candidate",
        "source": "https://github.com/DebarghaG/LeanGuard",
        "revision": run("git", "rev-parse", "HEAD", capture=True).stdout.strip(),
        "dirty": dirty,
        "toolchain": (ROOT / "lean-toolchain").read_text().strip(),
        "dependencies": json.loads((ROOT / "lake-manifest.json").read_text()),
        "platform": platform.system(),
        "architecture": platform.machine(),
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "audit_sha256": hashlib.sha256(audit.encode()).hexdigest(),
        "verification": "scripts/verify.py passed",
        "licensing": "See THIRD_PARTY_NOTICES; release permission must be established separately",
    }
    with tempfile.TemporaryDirectory(prefix="leanguard-release-") as directory:
        staging = Path(directory)
        (staging / "build-details.json").write_text(json.dumps(metadata, indent=2) + "\n")
        (staging / "proof-audit.txt").write_text(audit)
        notices = []
        for package in sorted((ROOT / ".lake/packages").iterdir()):
            if not package.is_dir():
                continue
            licenses = [p for p in package.glob("LICENSE*") if p.is_file()]
            notices.append(f"Dependency: {package.name}\n")
            if not licenses:
                notices.append("NO LICENSE FILE FOUND. Establish redistribution permission.\n")
            for license_file in licenses:
                notices.append(license_file.read_text())
        sysroot = Path(run("lean", "--print-prefix", capture=True).stdout.strip())
        for license_file in sorted(sysroot.glob("LICENSE*")):
            notices.append(f"Lean toolchain: {license_file.name}\n{license_file.read_text()}")
        (staging / "THIRD_PARTY_NOTICES").write_text("\n\n".join(notices))
        env = {
            **os.environ,
            "LEANGUARD_BUNDLE_BINARY": str(binary),
            "LEANGUARD_BUILD_METADATA": str(staging),
        }
        run(sys.executable, "-m", "build", "--sdist", "--wheel", "--outdir", str(output), env=env)
        for name in ("build-details.json", "proof-audit.txt", "THIRD_PARTY_NOTICES"):
            (output / name).write_bytes((staging / name).read_bytes())
    print(f"Verified candidates written to {output}; nothing published.")
    with tarfile.open(output / f"leanguard-policy-{version}.tar.gz", "w:gz") as archive:
        archive.add(ROOT / "skills/leanguard-policy", arcname="leanguard-policy")
        archive.add(ROOT / "LICENSE", arcname="leanguard-policy/LICENSE")


if __name__ == "__main__":
    main()
