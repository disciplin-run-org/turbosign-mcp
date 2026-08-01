"""Runtime settings, resolved fresh on every use.

Nothing here is read at import time. A machine with no credentials at all is a
normal, healthy first state — the server must still start and still list its
tools, or the agent cannot even discover the onboarding tools it needs to fix
the situation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import credentials
from .errors import NotConfiguredError

DEFAULT_MAX_FILE_MB = 10.0

# Deliberately sized to fit inside Hermes' 300s per-tool budget while staying
# well clear of it. See README, "Why these tools are synchronous".
DEFAULT_TIMEOUT_SECONDS = 90.0

SUPPORTED_EXTENSIONS: tuple[str, ...] = (".pdf", ".docx", ".pptx")


@dataclass(frozen=True)
class Settings:
    """A resolved view of this machine's configuration."""

    api_key: str | None
    org_id: str | None
    sender_email: str | None
    sender_name: str | None
    base_url: str
    sources: dict[str, str] = field(default_factory=dict)
    allowed_dirs: tuple[Path, ...] = ()
    max_file_bytes: int = int(DEFAULT_MAX_FILE_MB * 1024 * 1024)
    timeout: float = DEFAULT_TIMEOUT_SECONDS

    @property
    def missing(self) -> list[str]:
        """Required credentials that are not set, as env-var names."""
        out = []
        for key in credentials.REQUIRED_KEYS:
            if not getattr(self, key):
                out.append(credentials.ENV_BY_KEY[key])
            # end if
        # end for
        return out
    # end def

    @property
    def is_configured(self) -> bool:
        """Whether a send could be attempted at all."""
        return not self.missing
    # end def

    def require(self) -> None:
        """Raise :class:`NotConfiguredError` unless fully credentialled."""
        if self.missing:
            raise NotConfiguredError(self.missing)
        # end if
        return
    # end def
# end class


def _allowed_dirs() -> tuple[Path, ...]:
    """Roots a document may be read from or written to.

    Defaults to the user's home directory. This is a guard against an agent
    being talked into mailing ``/etc/`` to a third party, not a sandbox — the
    server runs as the user and could read those files anyway; the point is
    that a *document send* has a narrower legitimate range than the process.
    """
    raw = os.environ.get("TURBOSIGN_ALLOWED_DIRS", "")
    if not raw.strip():
        return (Path.home().resolve(),)
    # end if
    out = []
    for part in raw.split(os.pathsep):
        if part.strip():
            out.append(Path(part.strip()).expanduser().resolve())
        # end if
    # end for
    return tuple(out) or (Path.home().resolve(),)
# end def


def _float_env(name: str, default: float) -> float:
    """Read a float from the environment, ignoring anything unparseable."""
    try:
        value = float(os.environ[name])
    except (KeyError, ValueError):
        return default
    # end try
    return value if value > 0 else default
# end def


def candidate_settings(
    api_key: str,
    org_id: str,
    sender_email: str,
    sender_name: str | None = None,
    base_url: str | None = None,
    base: Settings | None = None,
) -> Settings:
    """Build settings for a specific set of credentials, for verification.

    Used before persisting anything, so the values under test are exactly the
    ones the caller supplied rather than whatever the environment currently
    resolves to. Shared by the ``configure`` CLI and the MCP tool so the two
    cannot drift.
    """
    from dataclasses import replace

    return replace(
        base or load_settings(),
        api_key=api_key,
        org_id=org_id,
        sender_email=sender_email,
        sender_name=sender_name,
        base_url=base_url or credentials.DEFAULT_BASE_URL,
    )
# end def


def load_settings() -> Settings:
    """Resolve settings from the environment and the credential store."""
    values: dict[str, str | None] = {}
    sources: dict[str, str] = {}
    for key in credentials.CREDENTIAL_KEYS:
        value, source = credentials.resolve(key)
        values[key] = value
        sources[key] = source
    # end for

    max_mb = _float_env("TURBOSIGN_MAX_FILE_MB", DEFAULT_MAX_FILE_MB)

    return Settings(
        api_key=values["api_key"],
        org_id=values["org_id"],
        sender_email=values["sender_email"],
        sender_name=values["sender_name"],
        base_url=values["base_url"] or credentials.DEFAULT_BASE_URL,
        sources=sources,
        allowed_dirs=_allowed_dirs(),
        max_file_bytes=int(max_mb * 1024 * 1024),
        timeout=_float_env("TURBOSIGN_TIMEOUT", DEFAULT_TIMEOUT_SECONDS),
    )
# end def
