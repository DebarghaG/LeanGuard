"""Regenerate the A2A gRPC stubs in python/leanguard/a2a_grpc.

The vendored a2a.proto is the unmodified file from the A2A specification release
named below. It imports google/api option protos that are not shipped as .proto
files by any Python package, so this script downloads them from the pinned
googleapis commit into a temporary directory, used only as a protoc include path.
The generated code depends on googleapis-common-protos at runtime.

Generated code refuses to load on a protobuf runtime older than the protoc that
produced it, so generate with the pinned grpcio-tools to keep the `a2a-grpc`
extra's protobuf floor at 5.29.

    .venv/bin/pip install grpcio-tools==1.71.2
    .venv/bin/python scripts/gen_a2a_grpc.py            # regenerate stubs
    .venv/bin/python scripts/gen_a2a_grpc.py --fetch    # also refetch a2a.proto
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
import urllib.request
from pathlib import Path

A2A_TAG = "v1.0.0"
A2A_PROTO_URL = (
    f"https://raw.githubusercontent.com/a2aproject/A2A/{A2A_TAG}/specification/a2a.proto"
)
A2A_PROTO_SHA256 = "4b74c0baa923ae0acb55474e548f1d6e5d3f83b80d757b65f8bf3e99a3c2257f"
GOOGLEAPIS_COMMIT = "b77e95d789147749264738d04e410df743d76631"
GOOGLEAPIS_PROTOS = ["annotations", "client", "field_behavior", "http", "launch_stage"]

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "python" / "leanguard" / "a2a_grpc"


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def main(argv: list[str]) -> int:
    from importlib import resources

    from grpc_tools import protoc

    proto = PACKAGE / "a2a.proto"
    if "--fetch" in argv:
        proto.write_bytes(fetch(A2A_PROTO_URL))
    digest = hashlib.sha256(proto.read_bytes()).hexdigest()
    if digest != A2A_PROTO_SHA256:
        print(f"a2a.proto sha256 {digest} does not match {A2A_TAG}; update A2A_PROTO_SHA256")
        return 1

    with tempfile.TemporaryDirectory() as include:
        api = Path(include) / "google" / "api"
        api.mkdir(parents=True)
        for name in GOOGLEAPIS_PROTOS:
            url = f"https://raw.githubusercontent.com/googleapis/googleapis/{GOOGLEAPIS_COMMIT}/google/api/{name}.proto"
            (api / f"{name}.proto").write_bytes(fetch(url))
        well_known = resources.files("grpc_tools") / "_proto"
        source = ROOT / "python"
        status = protoc.main(
            [
                "protoc",
                f"-I{source}",
                f"-I{include}",
                f"-I{well_known}",
                f"--python_out={source}",
                f"--pyi_out={source}",
                f"--grpc_python_out={source}",
                str(proto.relative_to(source)),
            ]
        )
    if status:
        return status
    for name in ("a2a_pb2.py", "a2a_pb2.pyi", "a2a_pb2_grpc.py"):
        if not (PACKAGE / name).is_file():
            print(f"protoc did not produce {name}")
            return 1
    print("regenerated a2a_pb2.py, a2a_pb2.pyi, a2a_pb2_grpc.py")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
