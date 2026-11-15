import io
import json
import threading
import zipfile
from contextlib import closing
from copy import deepcopy
from http.client import HTTPConnection
from pathlib import Path

import pytest
from leanguard.engine import default_binary
from leanguard.policy_review import verify_for_activation
from leanguard.workbench import OperatorServer, PolicyWorkbench

ROOT = Path(__file__).resolve().parents[1]


def test_operator_origin_authentication_and_stale_drafts(tmp_path):
    app = PolicyWorkbench(ROOT, tmp_path)
    with OperatorServer(app) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:

            def request(method, path, body=None, **headers):
                with closing(HTTPConnection("127.0.0.1", server.server_port)) as connection:
                    connection.request(method, path, body, headers)
                    response = connection.getresponse()
                    return response.status, dict(response.getheaders()), response.read()

            assert request("GET", "/api/state")[0] == 401
            assert request("GET", "/", Host="attacker.example")[0] == 421
            assert request("POST", "/session", Origin="https://attacker.example")[0] == 403
            assert (
                request("POST", "/session", Origin=server.origin, Authorization="Bearer wrong")[0]
                == 401
            )
            status, headers, _ = request(
                "POST", "/session", Origin=server.origin, Authorization="Bearer " + server.token
            )
            assert status == 200
            cookie = headers["Set-Cookie"].split(";", 1)[0]
            assert (
                "HttpOnly" in headers["Set-Cookie"] and "SameSite=Strict" in headers["Set-Cookie"]
            )
            status, _, body = request("GET", "/api/state", Cookie=cookie)
            assert status == 200
            state = json.loads(body)
            payload = json.dumps(
                {"revision": state["revision"], "document_text": json.dumps(state["document"])}
            )
            assert (
                request(
                    "POST",
                    "/api/draft",
                    payload,
                    Cookie=cookie,
                    Origin=server.origin,
                    **{"Content-Type": "application/json"},
                )[0]
                == 403
            )
            authenticated = {
                "Cookie": cookie,
                "Origin": server.origin,
                "X-LeanGuard-UI": "1",
                "Content-Type": "application/json",
            }
            assert request("POST", "/api/draft", payload, **authenticated)[0] == 200
            stale = json.dumps({"revision": "stale", "document_text": "{}"})
            assert request("POST", "/api/draft", stale, **authenticated)[0] == 400
            assert request("POST", "/api/execute", "{}", **authenticated)[0] == 400
            assert (
                request(
                    "POST",
                    "/api/draft",
                    "{}",
                    **{**authenticated, "Origin": "https://attacker.example"},
                )[0]
                == 403
            )
            assert request("GET", "/export/../../operator-review.key", Cookie=cookie)[0] == 400
            (tmp_path / "draft.json").write_text("external edit")
            assert request("POST", "/api/draft", payload, **authenticated)[0] == 400
            assert (tmp_path / "draft.json").read_text() == "external edit"
        finally:
            server.shutdown()
            thread.join()


def test_native_workbench_review_flow_and_private_export(tmp_path):
    app = PolicyWorkbench(ROOT, tmp_path)
    revision = app.revision()
    state = app.action("/api/compile", {"revision": revision})
    assert state["compiled"]
    corpus = state["corpus_text"]
    state = app.action("/api/scenarios", {"revision": revision, "corpus_text": corpus})
    assert [case["assessment"] for case in state["results"]["cases"]] == [
        "denied",
        "allowed",
        "denied",
    ]
    bundle_request = {
        "revision": revision,
        "corpus_sha256": state["results"]["corpus_sha256"],
        "corpus_text": corpus,
    }
    with pytest.raises(ValueError, match="current scenarios"):
        app.action("/api/bundle", {**bundle_request, "corpus_text": "{}"})
    state = app.action("/api/bundle", bundle_request)
    state = app.action(
        "/api/review",
        {
            "revision": revision,
            "bundle_sha256": state["bundle"]["bundle_sha256"],
            "decision": "accept",
        },
    )
    assert (
        verify_for_activation(state["bundle"]["directory"], state["review"], app.key)["domain"]
        == "documents"
    )
    data, _, _ = app.export("/export/review.zip")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert "review.json" in archive.namelist()
        assert "bundle/scenarios.json" not in archive.namelist()
        assert not any("key" in name for name in archive.namelist())
    document = deepcopy(state["document"])
    document["units"] = "cents"
    state = app.action("/api/draft", {"revision": revision, "document_text": json.dumps(document)})
    assert not state["compiled"] and state["bundle"] is None and state["review"] is None


def test_existing_native_pack_is_read_only(tmp_path):
    app = PolicyWorkbench(ROOT, tmp_path, domain="example", binary=default_binary())
    assert app.state()["document"] is None
    assert app.state()["inspection"]["domain"] == "example"
    with pytest.raises(ValueError, match="read-only"):
        app.action("/api/compile", {"revision": None})
    assert "operator-review.key" not in app.export("/export/inspection.json")[0].decode()
