import argparse
import json
import os
import tempfile
from pathlib import Path

from .engine import Engine
from .host import GuardHost


def main():
    parser = argparse.ArgumentParser(description="Native Lean agent guardrails")
    sub = parser.add_subparsers(dest="command", required=True)
    manifest = sub.add_parser("manifest")
    manifest.add_argument("domain")
    manifest.add_argument("--binary", type=Path)
    replay_parser = sub.add_parser("replay", help="Audit normalized chronological JSONL events")
    replay_parser.add_argument("domain")
    replay_parser.add_argument("events", type=Path)
    replay_parser.add_argument("--binary", type=Path)
    replay_parser.add_argument("--incomplete-history", action="store_true")
    sub.add_parser("demo")
    serve = sub.add_parser("mcp")
    serve.add_argument(
        "--domain", default="example", choices=["example", "retail", "airline", "telecom"]
    )
    serve.add_argument("--journal", type=Path, required=True)
    serve.add_argument("--principal", required=True)
    serve.add_argument("--session", required=True)
    serve.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--allowed-host", action="append", default=None)
    args = parser.parse_args()
    if args.command == "manifest":
        with Engine(args.domain, binary=args.binary) as engine:
            print(json.dumps(engine.manifest, indent=2))
    elif args.command == "replay":
        from .replay import replay

        with Engine(args.domain, binary=args.binary) as engine, args.events.open() as stream:
            events = (json.loads(line) for line in stream if line.strip())
            for result in replay(engine, events, history_complete=not args.incomplete_history):
                print(json.dumps(result))
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
                # Fixture standing in for a real, trusted confirmation UI.
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
            if args.transport == "stdio":
                build_server(host).run(transport="stdio")
            else:
                import uvicorn

                from .mcp_http import build_http_app

                app = build_http_app(
                    host,
                    token=os.environ.get("LEANGUARD_MCP_TOKEN", ""),
                    allowed_hosts=args.allowed_host,
                )
                uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
