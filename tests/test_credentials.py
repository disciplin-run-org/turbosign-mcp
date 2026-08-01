"""Credential resolution, the store, and masking.

The precedence rule tested here is the one the whole multi-machine design
rests on: the environment always wins, so an unattended box injecting
``${env:VAR}`` cannot have its identity changed by a tool call.
"""

from __future__ import annotations

import json
import os
import stat

from turbosign_mcp import credentials
from turbosign_mcp.config import load_settings


def test_nothing_configured_is_a_healthy_state(isolated_home):
    settings = load_settings()
    assert not settings.is_configured
    assert settings.missing == [
        "TURBODOCX_API_KEY",
        "TURBODOCX_ORG_ID",
        "TURBODOCX_SENDER_EMAIL",
    ]
    # It still resolves — no exception, no crash, tools remain listable.
    assert settings.base_url == credentials.DEFAULT_BASE_URL
# end def


def test_the_store_supplies_credentials(isolated_home):
    credentials.save_store(
        {"api_key": "k", "org_id": "o", "sender_email": "s@example.com"}
    )
    settings = load_settings()
    assert settings.is_configured
    assert settings.api_key == "k"
    assert settings.sources["api_key"] == "store"
# end def


def test_the_environment_beats_the_store(isolated_home, monkeypatch):
    credentials.save_store({"api_key": "from-store", "org_id": "o"})
    monkeypatch.setenv("TURBODOCX_API_KEY", "from-env")
    settings = load_settings()
    assert settings.api_key == "from-env"
    assert settings.sources["api_key"] == "env"
    # The store value is still there — it is overridden, not destroyed.
    assert credentials.load_store()["api_key"] == "from-store"
# end def


def test_the_store_is_written_owner_only(isolated_home):
    path = credentials.save_store({"api_key": "secret"})
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"
    dir_mode = stat.S_IMODE(os.stat(path.parent).st_mode)
    assert dir_mode == 0o700, f"expected 0700, got {oct(dir_mode)}"
# end def


def test_a_corrupt_store_is_treated_as_absent(isolated_home):
    credentials.save_store({"api_key": "k"})
    credentials.store_path().write_text("{ not json")
    # A broken file must not make the server unusable — the environment could
    # still be supplying working credentials.
    assert credentials.load_store() == {}
# end def


def test_unknown_keys_are_not_persisted(isolated_home):
    credentials.save_store({"api_key": "k", "sneaky": "value"})
    assert "sneaky" not in json.loads(credentials.store_path().read_text())
# end def


def test_saving_preserves_the_other_fields(isolated_home):
    credentials.save_store({"api_key": "k", "org_id": "o"})
    existing = credentials.load_store()
    existing.update({"sender_email": "s@example.com"})
    credentials.save_store(existing)
    assert credentials.load_store()["api_key"] == "k"
# end def


def test_clearing_removes_the_store(isolated_home):
    credentials.save_store({"api_key": "k"})
    assert credentials.clear_store() is True
    assert credentials.load_store() == {}
# end def


# -- masking ---------------------------------------------------------------


def test_masking_reveals_only_the_last_four():
    masked = credentials.mask("sk-abcdefghijklmnop")
    assert masked.endswith("mnop")
    assert "abcdefghijkl" not in masked
# end def


def test_masking_a_short_secret_reveals_nothing():
    assert set(credentials.mask("short")) == {"*"}
# end def


def test_masking_an_absent_secret_says_unset():
    assert credentials.mask(None) == "(unset)"
# end def


# -- onboarding URLs -------------------------------------------------------


def test_the_urls_have_working_defaults(isolated_home):
    assert credentials.app_url().startswith("https://")
    assert credentials.signup_url().startswith("https://")
# end def


def test_the_urls_are_overridable(isolated_home, monkeypatch):
    # The API-key deep link is documented as navigation, not a URL, so it has
    # to be changeable without a release.
    monkeypatch.setenv("TURBODOCX_APP_URL", "https://console.example.com/keys")
    assert credentials.app_url() == "https://console.example.com/keys"
# end def


def test_the_home_directory_is_overridable(isolated_home, monkeypatch, tmp_path):
    monkeypatch.setenv("TURBOSIGN_HOME", str(tmp_path / "elsewhere"))
    assert credentials.store_path().parent == tmp_path / "elsewhere"
# end def
