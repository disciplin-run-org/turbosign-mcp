"""The self-test, and the stdio transport itself.

A stdio server has no health URL, so ``--selftest`` is what a heal script or a
regression suite calls instead. It is also the only check that runs the real
subprocess rather than the in-memory transport — which is what catches a
server that imports fine but cannot actually serve.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

SERVER_CMD = [sys.executable, "-m", "turbosign_mcp.server"]


def _env_without_credentials(tmp_path) -> dict:
    """A pristine environment: no credentials anywhere."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("TURBODOCX_")}
    env["TURBOSIGN_HOME"] = str(tmp_path / "home")
    env["PYTHONPATH"] = str(
        __import__("pathlib").Path(__file__).parents[1] / "src"
    )
    return env
# end def


def test_selftest_passes_on_a_machine_with_no_credentials(tmp_path):
    # The fresh-box state. An uncredentialled machine is healthy, not broken —
    # if this ever exits non-zero, every heal check on a new box goes red for
    # no reason.
    result = subprocess.run(
        SERVER_CMD + ["--selftest"],
        capture_output=True,
        text=True,
        env=_env_without_credentials(tmp_path),
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "configured: no" in result.stdout
    assert "this is not an error" in result.stdout
# end def


def test_selftest_enumerates_every_tool(tmp_path):
    # Guards the FastMCP enumeration API, which is version-sensitive: an
    # upstream rename silently broke this once already.
    result = subprocess.run(
        SERVER_CMD + ["--selftest"],
        capture_output=True,
        text=True,
        env=_env_without_credentials(tmp_path),
        timeout=60,
    )
    assert "tools: 12" in result.stdout
    for name in ("turbosign_send", "turbosign_setup", "refresh_tools"):
        assert f"- {name}" in result.stdout
    # end for
# end def


def test_selftest_never_prints_the_api_key(tmp_path):
    env = _env_without_credentials(tmp_path)
    env["TURBODOCX_API_KEY"] = "sk-live-supersecretvalue"
    env["TURBODOCX_ORG_ID"] = "org-1"
    env["TURBODOCX_SENDER_EMAIL"] = "s@example.com"
    result = subprocess.run(
        SERVER_CMD + ["--selftest"],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert result.returncode == 0
    assert "supersecret" not in result.stdout
    assert "configured: yes" in result.stdout
# end def


def test_version_flag(tmp_path):
    result = subprocess.run(
        SERVER_CMD + ["--version"],
        capture_output=True, text=True,
        env=_env_without_credentials(tmp_path), timeout=60,
    )
    assert result.returncode == 0
    assert result.stdout.strip()
# end def


@pytest.mark.asyncio
async def test_the_stdio_transport_actually_serves(tmp_path):
    """Speak MCP to a real subprocess over stdio.

    Everything else uses the in-memory transport. This is the one test that
    proves the thing Hermes will actually launch works.
    """
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    env = _env_without_credentials(tmp_path)
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "turbosign_mcp.server"],
        env=env,
    )
    async with Client(transport) as client:
        tools = {tool.name for tool in await client.list_tools()}
        result = await client.call_tool("turbosign_setup", {})
    # end with

    assert "turbosign_send" in tools
    assert "not ready to send" in str(result.content[0].text)
# end def
