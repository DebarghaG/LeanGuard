#!/usr/bin/env bash
# Install the pinned source release and run its local demonstration.
set -euo pipefail
cd -- "$(dirname -- "$0")/.."

if [[ "$(uname -s)" != Linux ]]; then
  echo "This release candidate supports Linux." >&2
  exit 1
fi
for tool in python3 git curl; do
  command -v "$tool" >/dev/null || { echo "Required command: $tool" >&2; exit 1; }
done
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else "Python 3.12+ is required")'

export PATH="${ELAN_HOME:-$HOME/.elan}/bin:$PATH"
if ! command -v elan >/dev/null; then
  installer=$(mktemp)
  trap 'rm -f "$installer"' EXIT
  curl --proto '=https' --tlsv1.2 -fsSL \
    https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -o "$installer"
  sh "$installer" -y --default-toolchain none --no-modify-path
fi

# Lake fetches the exact LeanLTL/mathlib revisions in the dependency manifests.
lake exe cache get
lake build
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/leanguard demo
