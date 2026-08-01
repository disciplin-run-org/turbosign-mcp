"""Per-machine credential store and the onboarding URLs.

This server is installed on several machines, each with its own TurboDocx
account and sender address, so "which account is this box?" is a question the
server has to be able to answer.

Resolution order is deliberate and is the whole design:

1. ``TURBODOCX_*`` environment variables.
2. ``$TURBOSIGN_HOME/credentials.json`` (default ``~/.turbosign-mcp``).
3. Neither — reported as not-configured, never as a crash.

**Environment always wins.** On an unattended box (Hermes injecting
``${env:VAR}``) the key never passes through the agent's context and no tool
call can overwrite it. The store is the interactive path for a machine someone
is sitting at. Supporting both, with that precedence, is what lets one artifact
serve both cases.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# Credential fields, in the order a human is asked for them.
CREDENTIAL_KEYS: tuple[str, ...] = (
    "api_key",
    "org_id",
    "sender_email",
    "sender_name",
    "base_url",
)

# The three without which nothing can be sent.
REQUIRED_KEYS: tuple[str, ...] = ("api_key", "org_id", "sender_email")

ENV_BY_KEY: dict[str, str] = {
    "api_key": "TURBODOCX_API_KEY",
    "org_id": "TURBODOCX_ORG_ID",
    "sender_email": "TURBODOCX_SENDER_EMAIL",
    "sender_name": "TURBODOCX_SENDER_NAME",
    "base_url": "TURBODOCX_BASE_URL",
}

DEFAULT_BASE_URL = "https://api.turbodocx.com"

# TurboDocx documents the navigation to the API key ("Settings -> API Keys")
# but not a deep link, so these are overridable rather than hard-coded truths.
# See docs/VERIFICATION.md — pin the real deep link on first live login.
DEFAULT_APP_URL = "https://app.turbodocx.com"
DEFAULT_SIGNUP_URL = "https://www.turbodocx.com"

CREDENTIALS_FILENAME = "credentials.json"


def home_dir() -> Path:
    """Directory holding this machine's credential store."""
    return Path(os.environ.get("TURBOSIGN_HOME", "~/.turbosign-mcp")).expanduser()
# end def


def store_path() -> Path:
    """Full path to the credential store file."""
    return home_dir() / CREDENTIALS_FILENAME
# end def


def load_store() -> dict[str, str]:
    """Read the credential store, or an empty mapping if there isn't one.

    A malformed store is treated as absent rather than fatal: a corrupt file
    must not make the server unusable when the environment could still supply
    working credentials.
    """
    path = store_path()
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    # end try
    if not isinstance(data, dict):
        return {}
    # end if
    return {k: v for k, v in data.items() if k in CREDENTIAL_KEYS and isinstance(v, str)}
# end def


def save_store(values: dict[str, str]) -> Path:
    """Write the credential store with owner-only permissions.

    Permissions are set on both the directory (0700) and the file (0600), and
    the file is written before the values land in it, so the secret is never
    briefly world-readable.
    """
    directory = home_dir()
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)

    path = store_path()
    kept = {k: v for k, v in values.items() if k in CREDENTIAL_KEYS and v}

    # Create empty with the right mode first, then fill it.
    path.touch(mode=0o600, exist_ok=True)
    os.chmod(path, 0o600)
    path.write_text(json.dumps(kept, indent=2, sort_keys=True) + "\n")
    return path
# end def


def clear_store() -> bool:
    """Delete the credential store. Returns whether a file was removed."""
    path = store_path()
    try:
        path.unlink()
        return True
    except OSError:
        return False
    # end try
# end def


def mask(secret: str | None, keep: int = 4) -> str:
    """Render a secret safe to put in a tool result or a log line.

    Never reveals more than the last ``keep`` characters, and never reveals
    anything at all from a secret too short for that to be safe.
    """
    if not secret:
        return "(unset)"
    # end if
    if len(secret) <= keep + 2:
        return "*" * len(secret)
    # end if
    return "*" * 4 + secret[-keep:]
# end def


def resolve(key: str) -> tuple[str | None, str]:
    """Resolve one credential to ``(value, source)``.

    Source is ``"env"``, ``"store"``, ``"default"`` or ``"unset"`` — which is
    the part that matters when several machines each have their own account and
    you need to know where this one's identity came from.
    """
    env_name = ENV_BY_KEY[key]
    from_env = os.environ.get(env_name)
    if from_env:
        return from_env, "env"
    # end if

    from_store = load_store().get(key)
    if from_store:
        return from_store, "store"
    # end if

    if key == "base_url":
        return DEFAULT_BASE_URL, "default"
    # end if
    return None, "unset"
# end def


def app_url() -> str:
    """Console URL where the API key and organization id are found."""
    return os.environ.get("TURBODOCX_APP_URL", DEFAULT_APP_URL)
# end def


def signup_url() -> str:
    """URL for creating a TurboDocx account."""
    return os.environ.get("TURBODOCX_SIGNUP_URL", DEFAULT_SIGNUP_URL)
# end def
