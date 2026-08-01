"""turbosign-mcp — a thin stdio MCP server for the TurboSign e-signature API."""

from __future__ import annotations

from pathlib import Path


def _read_version() -> str:
    """Version from the VERSION file, which is the single source of truth."""
    for candidate in (Path("/app/VERSION"), Path(__file__).parents[2] / "VERSION"):
        try:
            return candidate.read_text().strip()
        except OSError:
            continue
        # end try
    # end for
    return "dev"
# end def


__version__ = _read_version()
