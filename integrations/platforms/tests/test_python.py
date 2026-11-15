"""Run in each platform's isolated SDK environment with LEANGUARD_PLATFORM set."""

import asyncio
import json
import os
import selectors
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
TOKEN = "test_credential_" + "x" * 32
PLATFORM = os.environ["LEANGUARD_PLATFORM"]


@pytest.fixture
def service(tmp_path):
    calls = tmp_path / "calls.json"
    with subprocess.Popen(
        [
            os.environ.get("LEANGUARD_TEST_PYTHON", str(ROOT / ".venv/bin/python")),
            str(ROOT / "tests/integrations/http_fixture.py"),
            "--calls-file",
            str(calls),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "python"), "LEANGUARD_MCP_TOKEN": TOKEN},
        stdout=subprocess.PIPE,
        text=True,
    ) as process:
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                assert selector.select(10), "Fixture startup timed out"
                hello = json.loads(process.stdout.readline())
            for _ in range(100):
                try:
                    urllib.request.urlopen(hello["url"], timeout=1)
                except urllib.error.HTTPError as error:
                    if error.code == 401:
                        break
                except urllib.error.URLError:
                    pass
                time.sleep(0.02)
            else:
                pytest.fail("Fixture readiness timed out")
            yield hello, lambda: json.loads(calls.read_text())
        finally:
            process.terminate()
            try:
                process.wait(5)
            except subprocess.TimeoutExpired:
                process.kill()


def test_real_platform_tool(service):
    hello, calls = service
    if PLATFORM == "dify":
        from dify_plugin.entities.tool import ToolRuntime
        from leanguard_remote.dify import LeanGuardProvider, LeanGuardTool

        credentials = {"url": hello["url"], "token": TOKEN}
        LeanGuardProvider().validate_credentials(credentials)
        tool = LeanGuardTool(
            ToolRuntime(credentials=credentials, user_id="ui-user", session_id="ui-session"), None
        )

        def invoke(action, arguments, proposal_id=None):
            messages = list(
                tool.invoke(
                    {
                        "action": action,
                        "arguments_json": json.dumps(arguments),
                        "proposal_id": proposal_id,
                    }
                )
            )
            return messages[0].message.json_object
    elif PLATFORM == "langflow":
        from leanguard_remote.langflow import LeanGuardTools

        component = LeanGuardTools(url=hello["url"], token=TOKEN)
        tools = component.build_tools()
        assert len(tools) == 1 and tools[0].name == "guarded_call"

        def invoke(action, arguments, proposal_id=None):
            return asyncio.run(
                tools[0].ainvoke(
                    {"action": action, "arguments": arguments, "proposal_id": proposal_id}
                )
            )
    else:
        pytest.fail(f"Unknown mandatory platform: {PLATFORM}")

    before = len(calls())
    assert invoke("write", {"value": "denied"})["allow"] is False
    assert len(calls()) == before
    assert invoke("read", {"reference": 9007199254740993})["outcome"] == "success"
    assert calls()[before][1]["reference"] == 9007199254740993
    assert invoke("write", {"value": "approved"}, hello["proposal"])["outcome"] == "success"
    assert invoke("write", {"value": "approved"}, hello["proposal"])["allow"] is False
    assert invoke("read", {"simulate_unknown": True})["outcome"] == "unknown"
    assert len(calls()) == before + 3


def test_bad_credentials_cannot_dispatch(service):
    from leanguard_remote import guarded_call

    hello, calls = service
    before = len(calls())
    with pytest.raises(ExceptionGroup) as failure:
        asyncio.run(guarded_call(hello["url"], "wrong_" + "x" * 32, "read", {}))

    def contains_unauthorized(error):
        if isinstance(error, BaseExceptionGroup):
            return any(contains_unauthorized(child) for child in error.exceptions)
        return "401" in str(error)

    assert contains_unauthorized(failure.value)
    assert len(calls()) == before


def test_dify_registration(monkeypatch):
    if PLATFORM != "dify":
        return
    from dify_plugin.config.config import DifyPluginEnv
    from dify_plugin.core.plugin_registration import PluginRegistration

    monkeypatch.chdir(ROOT / "integrations/platforms/dify")
    monkeypatch.syspath_prepend(str(ROOT / "integrations/platforms/dify"))
    registered = PluginRegistration(DifyPluginEnv())
    assert set(registered.tools_mapping) == {"leanguard"}
    assert set(registered.tools_mapping["leanguard"][2]) == {"guarded_call"}
