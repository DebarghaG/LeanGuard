import argparse
import json
import tempfile
from pathlib import Path

from .engine import Engine
from .host import GuardHost


def main():
    parser = argparse.ArgumentParser(description="Native Lean agent guardrails")
    sub = parser.add_subparsers(dest="command", required=True)
    manifest = sub.add_parser("manifest")
    manifest.add_argument("domain", choices=["example", "retail", "airline", "telecom"])
    sub.add_parser("demo")
    serve = sub.add_parser("mcp")
    serve.add_argument(
        "--domain", default="example", choices=["example", "retail", "airline", "telecom"]
    )
    serve.add_argument("--journal", type=Path, required=True)
    serve.add_argument("--principal", required=True)
    serve.add_argument("--session", required=True)
    args = parser.parse_args()
    if args.command == "manifest":
        with Engine(args.domain) as engine:
            print(json.dumps(engine.manifest, indent=2))
    elif args.command == "demo":
        from .demo import MemoryTools

        with tempfile.TemporaryDirectory(prefix="leanguard-demo-") as directory:
            adapter = MemoryTools()
            with GuardHost(
                "example",
                Path(directory) / "events.sqlite",
                adapter,
                principal="alice",
                session="demo",
            ) as host:
                print("Unapproved write:", host.execute("write", {"value": "updated"}))
                print("Read:", host.execute("read", {}))
                proposal = host.prepare("write", {"value": "updated"})
                # Deterministic fixture standing in for the separate trusted user UI.
                host.confirm(proposal.id, True)
                print(
                    "Approved fixture write:",
                    host.execute("write", {"value": "updated"}, proposal_id=proposal.id),
                )
                print("Backend calls:", [action for action, _ in adapter.calls])
    else:
        from .mcp_server import build_server

        if args.domain == "example":
            from .demo import MemoryTools

            adapter = MemoryTools()
            clock = None
        else:
            from .tau import TauAdapter

            adapter = TauAdapter(args.domain)
            clock = lambda: adapter.clock
        with GuardHost(
            args.domain,
            args.journal,
            adapter,
            principal=args.principal,
            session=args.session,
            clock=clock,
        ) as host:
            build_server(host).run(transport="stdio")


if __name__ == "__main__":
    main()
