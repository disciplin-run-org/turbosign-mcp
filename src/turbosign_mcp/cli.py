"""``turbosign-mcp configure`` — save credentials without an agent seeing them.

The MCP tool ``turbosign_configure`` is convenient but has one unavoidable
property: whatever you pass to it travels through the agent's context and is
written to that conversation's transcript on disk. For a scoped key on a test
account that is a fair trade. For a long-lived key, or a lifted session token
that can do everything the user can, it is not.

This is the same operation driven from a terminal instead: the key is read with
a hidden prompt, verified against the live API, and written straight to the
credential store. It is never echoed, never passed as a command-line argument,
and never enters any conversation.

**There is deliberately no --api-key flag.** A secret on a command line ends up
in shell history and in the process table, where any other user on the box can
read it with ps. Use the prompt, or --api-key-file for automated provisioning.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from . import credentials
from .api import TurboSignClient
from .config import candidate_settings, load_settings
from .errors import TurboSignError

# Rejected explicitly rather than silently ignored, so anyone reaching for the
# obvious flag learns why it does not exist instead of thinking it failed.
_FORBIDDEN_FLAGS = ("--api-key", "--apikey", "--token")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="turbosign-mcp configure",
        description=(
            "Save this machine's TurboDocx credentials. The API key is read "
            "from a hidden prompt and verified before anything is written."
        ),
    )
    parser.add_argument(
        "--api-key-file",
        metavar="PATH",
        help=(
            "Read the API key from a file instead of prompting, for automated "
            "provisioning. There is no --api-key flag on purpose: a secret in "
            "argv is visible in shell history and to ps."
        ),
    )
    parser.add_argument("--org-id", help="Organization id (x-rapiddocx-org-id).")
    parser.add_argument("--sender-email", help="Reply-to address on request emails.")
    parser.add_argument("--sender-name", help="Optional display name.")
    parser.add_argument("--base-url", help="Override the API base URL.")
    return parser
# end def


def _read_key_file(path_str: str) -> str:
    """Read an API key from a file, and complain if it looks world-readable."""
    path = Path(path_str).expanduser()
    try:
        raw = path.read_text()
    except OSError as exc:
        raise TurboSignError(
            f"Could not read the API key from {path}: {exc}",
            "Check the path and that the file is readable.",
        ) from exc
    # end try

    try:
        mode = path.stat().st_mode & 0o077
        if mode:
            print(
                f"warning: {path} is readable by other users (mode "
                f"{oct(path.stat().st_mode & 0o777)}). chmod 600 it.",
                file=sys.stderr,
            )
        # end if
    except OSError:
        pass  # permissions are advisory here; the read already succeeded
    # end try

    key = raw.strip()
    if not key:
        raise TurboSignError(
            f"{path} is empty.",
            "Put the API key in it, with no surrounding quotes.",
        )
    # end if
    return key
# end def


def run_configure(
    argv: list[str],
    *,
    secret_reader=None,
    line_reader=None,
) -> int:
    """Run the configure flow. Returns a process exit code.

    The readers are injectable so the flow can be tested without a terminal;
    by default the key comes from a hidden prompt and the rest from stdin.
    """
    for token in argv:
        name = token.split("=", 1)[0]
        if name in _FORBIDDEN_FLAGS:
            print(
                f"error: {name} does not exist, deliberately. A secret passed "
                "on the command line is recorded in your shell history and is "
                "visible to every other user on this machine via ps.\n"
                "Run 'turbosign-mcp configure' with no arguments to be "
                "prompted, or use --api-key-file for automation.",
                file=sys.stderr,
            )
            return 2
        # end if
    # end for

    args = _build_parser().parse_args(argv)
    ask_secret = secret_reader or (lambda p: getpass.getpass(p))
    ask_line = line_reader or (lambda p: input(p))

    try:
        if args.api_key_file:
            api_key = _read_key_file(args.api_key_file)
        else:
            api_key = ask_secret("TurboDocx API key (hidden): ").strip()
        # end if

        org_id = (args.org_id or ask_line("Organization id: ")).strip()
        sender_email = (
            args.sender_email or ask_line("Sender email (reply-to): ")
        ).strip()
        sender_name = (args.sender_name or "").strip()
        base_url = (args.base_url or "").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled. Nothing was saved.", file=sys.stderr)
        return 130
    except TurboSignError as exc:
        # An unreadable or empty --api-key-file, most likely. The operator gets
        # the sentence, not a traceback.
        print(f"error: {exc.message}\n  {exc.hint}", file=sys.stderr)
        return 1
    # end try

    missing = [
        label
        for label, value in (
            ("API key", api_key),
            ("organization id", org_id),
            ("sender email", sender_email),
        )
        if not value
    ]
    if missing:
        print(f"error: {', '.join(missing)} is required.", file=sys.stderr)
        return 2
    # end if

    print("Verifying against TurboSign...", file=sys.stderr)
    settings = candidate_settings(
        api_key=api_key,
        org_id=org_id,
        sender_email=sender_email,
        sender_name=sender_name or None,
        base_url=base_url or None,
    )
    try:
        ok, detail = TurboSignClient(settings).probe()
    except TurboSignError as exc:
        print(f"error: {exc.message}\n  {exc.hint}", file=sys.stderr)
        return 1
    # end try

    if not ok:
        print(
            f"error: those credentials were not accepted. {detail}\n"
            "  Nothing has been saved. Re-copy the key and organization id "
            "and try again.",
            file=sys.stderr,
        )
        return 1
    # end if

    stored = credentials.load_store()
    stored.update({"api_key": api_key, "org_id": org_id, "sender_email": sender_email})
    if sender_name:
        stored["sender_name"] = sender_name
    # end if
    if base_url:
        stored["base_url"] = base_url
    # end if
    path = credentials.save_store(stored)

    print(f"Verified and saved to {path} (mode 0600).")
    print(f"  api_key:      {credentials.mask(api_key)}")
    print(f"  org_id:       {org_id}")
    print(f"  sender_email: {sender_email}")

    # Precedence matters enough to say out loud: a stored key that an
    # environment variable is shadowing looks configured but is not the one
    # being used.
    if os.environ.get(credentials.ENV_BY_KEY["api_key"]):
        print(
            "\nnote: TURBODOCX_API_KEY is set in this environment and takes "
            "precedence over the file just written. The stored key will not "
            "be used until that variable is unset.",
            file=sys.stderr,
        )
    # end if

    if not load_settings().is_configured:
        print(
            "\nwarning: this machine still reports as unconfigured.",
            file=sys.stderr,
        )
        return 1
    # end if

    print("\nThis machine is ready. Next: turbosign_review() on a test PDF — "
          "it emails nobody.")
    return 0
# end def
