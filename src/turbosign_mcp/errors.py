"""Error types for turbosign-mcp.

The rule this module exists to enforce: an agent treats an error as an
observation and tries to recover from it. So every error carries a sentence
that says what to do next, not just what went wrong. Tools catch
``TurboSignError`` and hand ``.as_result()`` back to the caller — a traceback
is never a useful thing to give a language model.
"""

from __future__ import annotations


class TurboSignError(Exception):
    """An error the calling agent can act on.

    Args:
        message: What went wrong, in one sentence.
        hint: What to do about it. Name a tool or an argument where possible.
    """

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint
    # end def

    def as_result(self) -> dict:
        """Render as the ``{"ok": False, ...}`` shape every tool returns."""
        out: dict = {"ok": False, "error": self.message}
        if self.hint:
            out["hint"] = self.hint
        # end if
        return out
    # end def


class NotConfiguredError(TurboSignError):
    """Credentials are missing. Always points at the onboarding tool."""

    def __init__(self, missing: list[str]) -> None:
        super().__init__(
            "TurboSign is not configured on this machine yet — missing: "
            + ", ".join(missing)
            + ".",
            "Call turbosign_setup() for the sign-up and API-key URLs, then "
            "turbosign_configure() with the values you get.",
        )
        self.missing = missing
    # end def
