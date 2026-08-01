"""turbosign-mcp entry point — a stdio MCP server over the TurboSign API.

Stdio rather than HTTP: TurboSign is a stateless request/response API, so
there is no long-lived state to keep warm and nothing to gain from a container
and a port. The client launches the process; when it exits, nothing is left
behind.
"""

from __future__ import annotations

import sys

from fastmcp import FastMCP

from . import __version__
from .tools import onboarding, signing

SERVER_NAME = "turbosign"

SERVER_INSTRUCTIONS = """\
TurboSign: send PDF documents out for electronic signature, and track them.

FIRST RUN — if tools report the server is not configured, call
turbosign_setup(). It gives the URLs for creating a TurboDocx account and
finding the API key and organization id, then turbosign_configure() saves them
for this machine. turbosign_whoami() shows which account this machine sends as.

RECOMMENDED WORKFLOW
1. turbosign_review(file_path, recipients) — prepares the document and returns
   a preview URL WITHOUT emailing anyone. Do this the first time you send a
   new kind of document, and look at where the signature boxes landed.
2. turbosign_send(file_path, recipients) — the same call that actually emails
   the recipients. Keep the document_id it returns.
3. turbosign_status(document_id) — has anyone signed yet.
4. turbosign_download(document_id, output_path) — once complete, fetch the
   signed PDF.

Also: turbosign_void (cancel, reason required), turbosign_resend (chase a
recipient — get their id from turbosign_status), turbosign_audit_trail (who
opened it, and when).

PLACEMENT — where the signature boxes go. By default (placement="auto") the
server reads the PDF: if it finds anchor text like {Signature1} or {Date1} it
puts the fields exactly there; if it does not, it places a signature and date
box per recipient at the foot of the last page. A document written with anchors
gets exact placement for free, and any other PDF still works. The response
always says which strategy was used.

RECIPIENTS — "Bob Smith <bob@example.com>, ann@example.com" is enough. By
default everyone can sign at once; pass sequential=true to make them sign in
the order listed.

Sending emails a document to a third party and cannot be recalled — only the
void. turbosign_review sends nothing, so prefer it when unsure.

Call get_instructions() to re-read this at any time.
"""

mcp = FastMCP(SERVER_NAME, instructions=SERVER_INSTRUCTIONS)

onboarding.register_tools(mcp)
signing.register_tools(mcp)


def _selftest() -> int:
    """Report whether this installation is healthy, and how it is configured.

    Stdio servers have no health URL, so this is the equivalent: a deterministic
    check something like a heal script or a regression suite can call.

    A machine with no credentials is NOT a failure — an uncredentialled box is
    the normal state before setup, and the server is working correctly if it
    can still start and offer the onboarding tools.
    """
    from .config import load_settings
    from .credentials import mask

    print(f"turbosign-mcp {__version__}")

    try:
        import asyncio

        tools = asyncio.run(mcp.list_tools())
        names = sorted(getattr(t, "name", str(t)) for t in tools)
    except Exception as exc:  # a failure here means the server cannot serve
        print(f"FAIL: could not enumerate tools: {exc}", file=sys.stderr)
        return 1
    # end try

    if not names:
        print("FAIL: the server registered no tools.", file=sys.stderr)
        return 1
    # end if

    print(f"tools: {len(names)}")
    for name in names:
        print(f"  - {name}")
    # end for

    settings = load_settings()
    print(f"api_key: {mask(settings.api_key)} ({settings.sources.get('api_key')})")
    print(f"org_id: {settings.org_id or '(unset)'}")
    print(f"sender_email: {settings.sender_email or '(unset)'}")
    print(f"base_url: {settings.base_url}")

    if settings.is_configured:
        print("configured: yes")
    else:
        print("configured: no — run turbosign_setup() (this is not an error)")
    # end if

    return 0
# end def


def main() -> None:
    """Run the MCP server over stdio, or self-test and exit."""
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    # end if
    if "--version" in sys.argv:
        print(__version__)
        raise SystemExit(0)
    # end if
    mcp.run()
    return
# end def


if __name__ == "__main__":
    main()
# end if
