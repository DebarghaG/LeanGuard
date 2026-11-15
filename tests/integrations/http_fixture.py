"""Real HTTP/native-engine fixture for cross-language conformance tests."""

import argparse
import json
import os
import socket
import tempfile
from pathlib import Path

import uvicorn
from leanguard import GuardHost
from leanguard.demo import MemoryTools
from leanguard.mcp_http import build_http_app


class RecordedTools(MemoryTools):
    def __init__(self, calls_file):
        super().__init__()
        self.calls_file = calls_file
        self.calls_file.write_text("[]")

    def execute(self, action, arguments):
        result = super().execute(action, arguments)
        self.calls_file.write_text(json.dumps(self.calls))
        if arguments.get("simulate_unknown"):
            raise RuntimeError("fixture uncertainty")
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--calls-file", type=Path, required=True)
    args = parser.parse_args()
    adapter = RecordedTools(args.calls_file)
    with (
        tempfile.TemporaryDirectory(prefix="leanguard-http-test-") as directory,
        GuardHost(
            "example",
            Path(directory) / "events.sqlite",
            adapter,
            principal="test-human",
            session="cross-language",
        ) as host,
        socket.socket() as listener,
    ):
        # A trusted fixture user approves one exact write, outside the tool API.
        host.execute("read", {})
        proposal = host.prepare("write", {"value": "approved"})
        host.confirm(proposal.id, True)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        print(
            json.dumps({"url": f"http://127.0.0.1:{port}/mcp", "proposal": proposal.id}), flush=True
        )
        app = build_http_app(host, token=os.environ["LEANGUARD_MCP_TOKEN"])
        server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        server.run(sockets=[listener])


if __name__ == "__main__":
    main()
