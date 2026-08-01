"""The `turbosign-mcp configure` subcommand.

Its whole reason to exist is that the key never enters an agent's context, so
the tests that matter most are the ones asserting it is never echoed and never
accepted on a command line.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys

import httpx
import pytest
import respx

from turbosign_mcp import credentials
from turbosign_mcp.cli import run_configure

BASE = "https://api.turbodocx.test"
KEY = "sk-live-abcdefghijklmnop"


def _readers(key=KEY, lines=("org-1", "sender@example.com")):
    """Injected stand-ins for the hidden prompt and stdin."""
    remaining = list(lines)
    return {
        "secret_reader": lambda prompt: key,
        "line_reader": lambda prompt: remaining.pop(0),
    }
# end def


def _mock_ok():
    respx.get(url__regex=r".*/turbosign/documents/.*/status").mock(
        return_value=httpx.Response(404, json={"message": "Not found"})
    )
# end def


def _mock_bad():
    respx.get(url__regex=r".*/turbosign/documents/.*/status").mock(
        return_value=httpx.Response(401, json={"message": "Unauthorized"})
    )
# end def


@respx.mock
def test_it_verifies_then_saves(isolated_home, capsys):
    _mock_ok()
    code = run_configure(["--base-url", BASE], **_readers())
    assert code == 0
    stored = credentials.load_store()
    assert stored["api_key"] == KEY
    assert stored["org_id"] == "org-1"
    assert stored["sender_email"] == "sender@example.com"
# end def


@respx.mock
def test_it_never_prints_the_key(isolated_home, capsys):
    _mock_ok()
    run_configure(["--base-url", BASE], **_readers())
    captured = capsys.readouterr()
    assert KEY not in captured.out
    assert KEY not in captured.err
    # A masked fingerprint is fine, and is what the operator confirms against.
    assert "mnop" in captured.out
# end def


@respx.mock
def test_a_bad_key_is_not_saved(isolated_home, capsys):
    _mock_bad()
    code = run_configure(["--base-url", BASE], **_readers())
    assert code == 1
    # The point of verifying first: a key that does not work never lands.
    assert credentials.load_store() == {}
    assert "not accepted" in capsys.readouterr().err
# end def


@respx.mock
def test_the_store_is_owner_only(isolated_home):
    _mock_ok()
    run_configure(["--base-url", BASE], **_readers())
    mode = stat.S_IMODE(os.stat(credentials.store_path()).st_mode)
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"
# end def


@respx.mock
def test_flags_can_supply_everything_but_the_key(isolated_home):
    _mock_ok()
    code = run_configure(
        ["--base-url", BASE, "--org-id", "o9", "--sender-email", "s@example.com",
         "--sender-name", "Test Co"],
        secret_reader=lambda p: KEY,
        line_reader=lambda p: pytest.fail("should not have prompted"),
    )
    assert code == 0
    assert credentials.load_store()["sender_name"] == "Test Co"
# end def


@respx.mock
def test_the_key_can_come_from_a_file(isolated_home, tmp_path):
    _mock_ok()
    key_file = tmp_path / "key.txt"
    key_file.write_text(KEY + "\n")
    os.chmod(key_file, 0o600)
    code = run_configure(
        ["--base-url", BASE, "--api-key-file", str(key_file),
         "--org-id", "o", "--sender-email", "s@example.com"],
        secret_reader=lambda p: pytest.fail("should not have prompted"),
        line_reader=lambda p: pytest.fail("should not have prompted"),
    )
    assert code == 0
    assert credentials.load_store()["api_key"] == KEY
# end def


def test_a_world_readable_key_file_is_called_out(isolated_home, tmp_path, capsys):
    key_file = tmp_path / "key.txt"
    key_file.write_text(KEY)
    os.chmod(key_file, 0o644)
    with respx.mock:
        _mock_ok()
        run_configure(
            ["--base-url", BASE, "--api-key-file", str(key_file),
             "--org-id", "o", "--sender-email", "s@example.com"],
        )
    # end with
    assert "readable by other users" in capsys.readouterr().err
# end def


def test_an_empty_key_file_says_so(isolated_home, tmp_path, capsys):
    key_file = tmp_path / "key.txt"
    key_file.write_text("   \n")
    code = run_configure(
        ["--api-key-file", str(key_file), "--org-id", "o",
         "--sender-email", "s@example.com"],
    )
    assert code == 1
    assert "is empty" in capsys.readouterr().err
# end def


@pytest.mark.parametrize("flag", ["--api-key", "--apikey", "--token"])
def test_passing_the_key_in_argv_is_refused(isolated_home, flag, capsys):
    # A secret in argv lands in shell history and is visible to ps. Refusing
    # loudly teaches that; silently ignoring the flag would not.
    code = run_configure([flag, KEY])
    assert code == 2
    err = capsys.readouterr().err
    assert "deliberately" in err
    assert "ps" in err
    assert credentials.load_store() == {}
# end def


@respx.mock
def test_it_warns_when_the_environment_shadows_the_stored_key(
    isolated_home, monkeypatch, capsys
):
    # A stored key that an env var overrides looks configured but is not the
    # one in use — worth saying out loud rather than letting it confuse later.
    _mock_ok()
    monkeypatch.setenv("TURBODOCX_API_KEY", "from-env")
    run_configure(["--base-url", BASE], **_readers())
    assert "takes precedence" in capsys.readouterr().err
# end def


@respx.mock
def test_cancelling_at_the_prompt_saves_nothing(isolated_home, capsys):
    def cancel(prompt):
        raise KeyboardInterrupt
    # end def

    code = run_configure(["--base-url", BASE], secret_reader=cancel)
    assert code == 130
    assert credentials.load_store() == {}
    assert "Nothing was saved" in capsys.readouterr().err
# end def


@respx.mock
def test_a_blank_key_is_refused_before_any_network_call(isolated_home, capsys):
    code = run_configure(["--base-url", BASE], secret_reader=lambda p: "  ",
                         line_reader=lambda p: "x")
    assert code == 2
    assert "required" in capsys.readouterr().err
# end def


@respx.mock
def test_configure_preserves_other_stored_fields(isolated_home):
    _mock_ok()
    credentials.save_store({"sender_name": "Existing Co"})
    run_configure(["--base-url", BASE], **_readers())
    assert credentials.load_store()["sender_name"] == "Existing Co"
# end def


# -- the real subcommand, end to end --------------------------------------


def test_the_subcommand_is_reachable_from_the_entry_point(tmp_path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("TURBODOCX_")}
    env["TURBOSIGN_HOME"] = str(tmp_path / "home")
    env["PYTHONPATH"] = str(__import__("pathlib").Path(__file__).parents[1] / "src")

    result = subprocess.run(
        [sys.executable, "-m", "turbosign_mcp.server", "configure", "--help"],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert result.returncode == 0
    # Match single words — argparse rewraps help text to the terminal width,
    # so any multi-word assertion here is a flake waiting to happen.
    assert "prompt" in result.stdout
    assert "--api-key-file" in result.stdout
    # The absence of a bare --api-key flag IS the security property. Check the
    # usage synopsis specifically — the help *body* mentions the flag by name
    # to explain why it does not exist, so a whole-output match is self-
    # defeating. argparse renders an accepted option as "[--api-key API_KEY]".
    assert "[--api-key " not in result.stdout
# end def
