"""Loopback-only, capability-authenticated operator UI for policy review."""

import argparse
import hmac
import io
import json
import secrets
import subprocess
import threading
import uuid
import zipfile
from copy import deepcopy
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path

from .engine import Engine, canonical, digest
from .inspection import inspect_policy
from .policy_authoring import (
    compile_document,
    example_document,
    generate_lean,
    load_json,
    validate_document,
)
from .policy_review import (
    compare_policies,
    create_bundle,
    create_review_key,
    record_review,
    run_scenarios,
    verify_bundle,
)


def example_scenarios():
    def event(kind, action, time, **extra):
        return {
            "id": f"{kind}-{time}",
            "time": time,
            "kind": kind,
            "principal": "review-user",
            "session": "example",
            "action": action,
            "resource": "document",
            "binding": "",
            "amount": 0,
            "input": {},
            "facts": {},
            **extra,
        }

    read = [event("dispatch", "read", 800, id="read"), event("success", "read", 801, id="read")]
    request = event("request", "write", 1000, binding="review-binding", input={"value": "new text"})
    return {
        "format": "leanguard.scenarios",
        "version": 1,
        "cases": [
            {
                "id": "without-approval",
                "request": deepcopy(request),
                "history": deepcopy(read),
                "history_complete": True,
                "missing_evidence": [],
            },
            {
                "id": "approved-write",
                "request": deepcopy(request),
                "history": [
                    *deepcopy(read),
                    event("confirmed", "write", 990, binding="review-binding"),
                ],
                "history_complete": True,
                "missing_evidence": [],
            },
            {
                "id": "expired-approval",
                "request": deepcopy(request),
                "history": [
                    event("confirmed", "write", 600, binding="review-binding"),
                    *deepcopy(read),
                ],
                "history_complete": True,
                "missing_evidence": [],
            },
        ],
    }


class PolicyWorkbench:
    page = "workbench.html"

    def __init__(self, project, directory, *, domain=None, binary=None):
        self.project, self.directory = Path(project).resolve(), Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = threading.RLock()
        self.path = self.directory / "draft.json"
        self.document = (
            None
            if domain
            else (
                validate_document(load_json(self.path.read_text()))
                if self.path.exists()
                else example_document()
            )
        )
        self.disk_revision = digest(self.path.read_text()) if self.path.exists() else None
        self.inspection = None
        if domain:
            with Engine(domain, binary) as engine:
                self.inspection = inspect_policy(engine)
        self.compiled = None
        self.baseline = None
        self.corpus = example_scenarios()
        self.results = None
        self.comparison = None
        self.bundle = None
        self.review = None
        self.key = self.directory / "operator-review.key"
        if not self.key.exists():
            create_review_key(self.key)

    def revision(self):
        return digest(self.document) if self.document is not None else None

    def is_compiled(self):
        return (
            self.compiled is not None
            and self.compiled["build"]["document_sha256"] == self.revision()
        )

    def state(self):
        return {
            "document": self.document,
            "revision": self.revision(),
            "lean": generate_lean(self.document) if self.document is not None else None,
            "inspection": self.inspection,
            "compiled": self.is_compiled(),
            "corpus_text": json.dumps(self.corpus, indent=2),
            "results": self.results,
            "comparison": self.comparison,
            "bundle": self.bundle,
            "review": self.review,
            "stage": "Reviewed"
            if self.review
            else "Ready for review"
            if self.bundle
            else "Compiled"
            if self.is_compiled()
            else "Draft"
            if self.document
            else "Read-only inspection",
        }

    def _revision(self, payload):
        if payload.get("revision") != self.revision():
            raise ValueError("The draft changed in another window. Reload before saving.")

    def _compiled(self, payload):
        self._revision(payload)
        if not self.is_compiled():
            raise ValueError("Compile this exact draft first")

    def _save(self, document):
        current = digest(self.path.read_text()) if self.path.exists() else None
        if current != self.disk_revision:
            raise ValueError(
                "draft.json changed outside this window. Restart to load it; no edit was overwritten."
            )
        document = validate_document(document)
        text = json.dumps(document, indent=2) + "\n"
        pending = self.path.with_suffix(".pending")
        pending.write_text(text)
        pending.replace(self.path)
        self.disk_revision = digest(text)
        self.document = document
        self.results = self.comparison = self.bundle = self.review = None

    def action(self, path, payload):
        if path == "/api/new":
            self._revision(payload)
            self._save(example_document())
            self.compiled = self.baseline = self.inspection = None
        elif path == "/api/draft":
            self._revision(payload)
            self._save(load_json(payload["document_text"]))
        elif path == "/api/compile":
            self._revision(payload)
            if self.document is None:
                raise ValueError("Native inspection is read-only; start a separate template")
            directory = self.directory / "builds" / uuid.uuid4().hex
            result = compile_document(self.document, directory, self.project)
            self.baseline, self.compiled = self.compiled, result
            self.inspection = result["inspection"]
            self.results = self.comparison = self.bundle = self.review = None
        elif path == "/api/scenarios":
            self._compiled(payload)
            corpus = load_json(payload["corpus_text"])
            results = run_scenarios(self.compiled["binary"], self.document["name"], corpus)
            comparison = None
            if self.baseline:
                comparison = compare_policies(
                    self.baseline["binary"],
                    self.baseline["inspection"]["domain"],
                    self.compiled["binary"],
                    self.document["name"],
                    corpus,
                )
            self.corpus, self.results, self.comparison = corpus, results, comparison
            self.bundle = self.review = None
        elif path == "/api/bundle":
            self._compiled(payload)
            if (
                self.results is None
                or payload.get("corpus_sha256") != self.results["corpus_sha256"]
                or digest(load_json(payload["corpus_text"])) != self.results["corpus_sha256"]
            ):
                raise ValueError("Run the current scenarios before creating a review bundle")
            include = payload.get("include_scenario_data", False)
            if type(include) is not bool:
                raise ValueError("Choose whether to include private scenario data")
            self.bundle = create_bundle(
                self.compiled["directory"],
                self.directory / "bundles" / uuid.uuid4().hex,
                self.corpus,
                include_scenario_data=include,
            )
            self.review = None
        elif path == "/api/review":
            self._compiled(payload)
            if not self.bundle or payload.get("bundle_sha256") != self.bundle["bundle_sha256"]:
                raise ValueError("Review must match this exact bundle")
            self.review = record_review(self.bundle["directory"], payload["decision"], self.key)
            reviews = self.directory / "reviews"
            reviews.mkdir(exist_ok=True)
            (reviews / f"{uuid.uuid4().hex}.json").write_text(canonical(self.review) + "\n")
        else:
            raise ValueError("Unknown operator action")
        return self.state()

    def export(self, path):
        if path == "/export/policy.json" and self.document:
            return json.dumps(self.document, indent=2).encode(), "policy.json", "application/json"
        if path == "/export/Policy.lean" and self.document:
            return generate_lean(self.document).encode(), "Policy.lean", "text/plain"
        if path == "/export/inspection.json" and self.inspection:
            return (
                json.dumps(self.inspection, indent=2).encode(),
                "inspection.json",
                "application/json",
            )
        if path == "/export/review.zip" and self.bundle:
            directory = Path(self.bundle["directory"])
            verify_bundle(directory)
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                for item in sorted(directory.iterdir()):
                    archive.write(item, f"bundle/{item.name}")
                if self.review:
                    archive.writestr("review.json", canonical(self.review) + "\n")
            return buffer.getvalue(), "leanguard-review.zip", "application/zip"
        raise ValueError("This export is not available yet")


def _browser_numbers(value):
    """Display large native integers exactly; JSON downloads retain native types."""
    if type(value) is int and abs(value) > 2**53 - 1:
        return str(value)
    if isinstance(value, dict):
        return {key: _browser_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_browser_numbers(item) for item in value]
    return value


class OperatorServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, app, port=0):
        self.app = app
        self.token = secrets.token_urlsafe(32)
        self.cookie = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), OperatorHandler)
        self.origin = f"http://127.0.0.1:{self.server_port}"

    @property
    def url(self):
        return f"{self.origin}/#{self.token}"


class OperatorHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # Operator capabilities and policy contents must not enter access logs.

    def _send(self, status, data, content_type="application/json", *, cookie=False, filename=None):
        self.send_response(status)
        self.send_header(
            "Content-Type",
            content_type + ("; charset=utf-8" if content_type != "application/zip" else ""),
        )
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        )
        if cookie:
            self.send_header(
                "Set-Cookie",
                f"leanguard_operator={self.server.cookie}; HttpOnly; SameSite=Strict; Path=/",
            )
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status, value, **kwargs):
        self._send(status, canonical(_browser_numbers(value)).encode(), **kwargs)

    def _host(self):
        return self.headers.get_all("Host") == [self.server.origin.removeprefix("http://")]

    def _authenticated(self):
        try:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            value = cookies.get("leanguard_operator")
            return value is not None and hmac.compare_digest(
                value.value.encode(), self.server.cookie.encode()
            )
        except CookieError:
            return False

    def do_GET(self):
        if not self._host():
            self._json(421, {"error": "Invalid operator host"})
            return
        assets = {
            "/": self.server.app.page,
            "/workbench.js": "workbench.js",
            "/approval.js": "approval.js",
            "/workbench.css": "workbench.css",
        }
        if self.path in assets:
            name = assets[self.path]
            mime = (
                "text/html"
                if name.endswith("html")
                else "text/css"
                if name.endswith("css")
                else "text/javascript"
            )
            asset = files("leanguard").joinpath("workbench_assets", name)
            if not asset.is_file():
                self._json(404, {"error": "Not found"})
                return
            self._send(200, asset.read_bytes(), mime)
            return
        if not self._authenticated():
            self._json(401, {"error": "Open the private operator link printed by the server"})
            return
        try:
            with self.server.app.lock:
                if self.path == "/api/state":
                    self._json(200, self.server.app.state())
                elif self.path.startswith("/export/"):
                    data, name, mime = self.server.app.export(self.path)
                    self._send(200, data, mime, filename=name)
                else:
                    self._json(404, {"error": "Not found"})
        except (ValueError, OSError) as error:
            self._json(400, {"error": str(error)})

    def do_POST(self):
        if not self._host() or self.headers.get("Origin") != self.server.origin:
            self._json(403, {"error": "Operator requests must come from this origin"})
            return
        if self.path == "/session":
            supplied = self.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied.encode(), ("Bearer " + self.server.token).encode()):
                self._json(401, {"error": "Invalid operator capability"})
                return
            self._json(200, {"ready": True}, cookie=True)
            return
        if not self._authenticated() or self.headers.get("X-LeanGuard-UI") != "1":
            self._json(403, {"error": "Operator authentication required"})
            return
        if self.headers.get("Content-Type") != "application/json" or self.headers.get(
            "Transfer-Encoding"
        ):
            self._json(415, {"error": "Use a bounded JSON request"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 2 * 1024 * 1024:
                raise ValueError("Operator requests must be between 1 byte and 2 MiB")
            payload = load_json(self.rfile.read(length).decode())
            if not isinstance(payload, dict):
                raise TypeError("Expected an object")
            with self.server.app.lock:
                result = self.server.app.action(self.path, payload)
            self._json(200, result)
        except (
            ValueError,
            TypeError,
            KeyError,
            OSError,
            RuntimeError,
            subprocess.SubprocessError,
        ) as error:
            self._json(400, {"error": str(error)})


def main():
    parser = argparse.ArgumentParser(
        description="Local human policy workbench; never expose its capability to agents"
    )
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--inspect", metavar="DOMAIN")
    parser.add_argument("--binary", type=Path)
    args = parser.parse_args()
    app = PolicyWorkbench(args.project, args.workspace, domain=args.inspect, binary=args.binary)
    with OperatorServer(app, args.port) as server:
        print(server.url, flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
