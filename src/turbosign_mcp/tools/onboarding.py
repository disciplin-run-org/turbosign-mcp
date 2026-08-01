"""Onboarding tools — getting a fresh machine credentialled.

This server is installed on several machines, each with its own TurboDocx
account and sender address, so "go and get a key" is part of the product rather
than a line in the README.
"""

from __future__ import annotations

import webbrowser

from fastmcp import Context, FastMCP

from .. import credentials
from ..api import TurboSignClient
from ..config import candidate_settings, load_settings
from ..errors import TurboSignError


def _source_note(source: str) -> str:
    """Explain where a value came from, in words rather than jargon."""
    return {
        "env": "environment variable",
        "store": "this machine's credential file",
        "default": "built-in default",
        "unset": "not set",
    }.get(source, source)
# end def


def register_tools(mcp: FastMCP) -> None:
    """Register the onboarding tools."""

    @mcp.tool
    def turbosign_setup(open_browser: bool = False) -> str:
        """Start here on a machine that has never sent a signature request.

        Reports which credentials are missing and where the present ones came
        from, then gives the URLs for creating a TurboDocx account and finding
        the API key and organization id. Follow the URLs, then call
        turbosign_configure() with the three values.

        Set open_browser=True to also try opening the console locally — it is
        best-effort and reports whether it worked, since a server without a
        desktop has no browser to open.
        """
        settings = load_settings()
        lines: list[str] = ["TurboSign setup", "=" * 15, ""]

        if settings.is_configured:
            lines.append("This machine is already configured:")
        else:
            lines.append("This machine is not ready to send yet:")
        # end if

        for key in credentials.CREDENTIAL_KEYS:
            value = getattr(settings, key, None)
            source = settings.sources.get(key, "unset")
            required = key in credentials.REQUIRED_KEYS
            if key == "api_key":
                shown = credentials.mask(value)
            else:
                shown = value or ("(not set)" if required else "(optional, not set)")
            # end if
            mark = "ok " if value else ("MISSING" if required else "   ")
            lines.append(f"  [{mark}] {key}: {shown}  <- {_source_note(source)}")
        # end for

        lines += [
            "",
            "Where to get the missing values:",
            f"  1. No account yet?  Sign up at {credentials.signup_url()}",
            f"  2. Already have one? Open the console at {credentials.app_url()}",
            "  3. Go to Settings -> API Keys, and generate or copy the access token.",
            "  4. Copy the organization id from the same Settings page.",
            "",
            "Then call:",
            "  turbosign_configure(api_key=..., org_id=..., sender_email=...)",
            "",
            "sender_email is the reply-to address on the signature request "
            "emails, and TurboSign rejects sends without it.",
        ]

        if open_browser:
            try:
                opened = webbrowser.open(credentials.app_url())
            except Exception:
                opened = False
            # end try
            lines.append("")
            lines.append(
                "Opened the console in a browser."
                if opened
                else "Could not open a browser on this machine — use the URL above."
            )
        # end if

        if settings.sources.get("api_key") == "env":
            lines += [
                "",
                "Note: the API key here comes from the environment, which "
                "takes precedence. turbosign_configure() would be stored but "
                "not used until that variable is unset.",
            ]
        # end if

        return "\n".join(lines)
    # end def

    @mcp.tool
    def turbosign_configure(
        api_key: str,
        org_id: str,
        sender_email: str,
        sender_name: str = "",
        base_url: str = "",
    ) -> dict:
        """Save this machine's TurboDocx credentials after checking they work.

        The credentials are verified against the live API before anything is
        written, so a mistyped key fails here rather than on your first real
        send. They are stored owner-only in ~/.turbosign-mcp/credentials.json.

        Get the values from turbosign_setup(). sender_email is the reply-to
        address recipients see. sender_name is optional and defaults to the
        name on the API key. base_url is only for a non-production endpoint.

        The key is never echoed back — only a masked fingerprint.

        PRIVACY: whatever you pass here travels through this conversation and
        is written to its transcript on disk. For a scoped key on a test
        account that is usually fine. For a long-lived key, or a session token
        that can do everything the user can, tell the human to run this in
        their own terminal instead — same verification, same store, and the
        key never enters the conversation:

            turbosign-mcp configure
        """
        pending = {
            "api_key": api_key.strip(),
            "org_id": org_id.strip(),
            "sender_email": sender_email.strip(),
        }
        if sender_name.strip():
            pending["sender_name"] = sender_name.strip()
        # end if
        if base_url.strip():
            pending["base_url"] = base_url.strip()
        # end if

        for key in credentials.REQUIRED_KEYS:
            if not pending.get(key):
                return TurboSignError(
                    f"{key} is required.",
                    "Call turbosign_setup() for where to find it.",
                ).as_result()
            # end if
        # end for

        # Verify against the live API using exactly these values, not the
        # resolved ones — writing a key that does not work is the failure this
        # tool exists to prevent.
        candidate = candidate_settings(
            api_key=pending["api_key"],
            org_id=pending["org_id"],
            sender_email=pending["sender_email"],
            sender_name=pending.get("sender_name"),
            base_url=pending.get("base_url"),
        )

        try:
            ok, detail = TurboSignClient(candidate).probe()
        except TurboSignError as exc:
            return exc.as_result()
        # end try

        if not ok:
            return TurboSignError(
                f"Those credentials were not accepted. {detail}",
                "Re-copy the API key and organization id from Settings -> "
                "API Keys; nothing has been saved.",
            ).as_result()
        # end if

        existing = credentials.load_store()
        existing.update(pending)
        path = credentials.save_store(existing)

        return {
            "ok": True,
            "message": "Credentials verified against TurboSign and saved.",
            "stored_at": str(path),
            "api_key": credentials.mask(pending["api_key"]),
            "org_id": pending["org_id"],
            "sender_email": pending["sender_email"],
            "note": (
                "Environment variables still take precedence over this file."
                if load_settings().sources.get("api_key") == "env"
                else "This machine is ready to send."
            ),
        }
    # end def

    @mcp.tool
    def turbosign_whoami(verify: bool = True) -> dict:
        """Show which TurboDocx account this machine sends as.

        Reports the masked API key, organization id, sender address, and where
        each value was resolved from — useful when the same server is
        installed on several machines with different accounts. With
        verify=True it also checks the credentials against the live API.
        """
        settings = load_settings()
        result: dict = {
            "ok": True,
            "configured": settings.is_configured,
            "api_key": credentials.mask(settings.api_key),
            "org_id": settings.org_id,
            "sender_email": settings.sender_email,
            "sender_name": settings.sender_name,
            "base_url": settings.base_url,
            "sources": {k: _source_note(v) for k, v in settings.sources.items()},
            "credential_file": str(credentials.store_path()),
        }
        if settings.missing:
            result["missing"] = settings.missing
            result["hint"] = "Call turbosign_setup() to get credentialled."
            return result
        # end if

        if verify:
            try:
                ok, detail = TurboSignClient(settings).probe()
                result["credentials_valid"] = ok
                result["verification"] = detail
            except TurboSignError as exc:
                result["credentials_valid"] = False
                result["verification"] = exc.message
            # end try
        # end if
        return result
    # end def

    @mcp.tool
    def get_instructions() -> str:
        """Return this server's usage instructions and recommended workflow.

        Call this after a context compaction, or whenever it is unclear which
        tool to reach for.
        """
        from ..server import SERVER_INSTRUCTIONS

        return SERVER_INSTRUCTIONS
    # end def

    @mcp.tool
    async def refresh_tools(ctx: Context) -> str:
        """Refresh the client's cached tool list after a server restart or
        upgrade. Call this instead of falling back to raw HTTP requests."""
        from mcp import types as mcp_types

        await ctx.send_notification(mcp_types.ToolListChangedNotification())
        return "Tool list refreshed. New and changed tools are now available."
    # end def
    # The `ctx: Context` annotation is mandatory — without it FastMCP treats
    # ctx as a required caller argument and every invocation fails.

    return
# end def
