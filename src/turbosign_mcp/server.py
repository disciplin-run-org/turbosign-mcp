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
from .placement import ANCHOR_GUIDANCE
from .tools import onboarding, signing

SERVER_NAME = "turbosign"

SERVER_INSTRUCTIONS = """\
TurboSign: send PDF documents out for electronic signature, and track them.

FIRST RUN — if tools report the server is not configured, call
turbosign_setup(). It gives the URLs for creating a TurboDocx account and
finding the API key and organization id, then turbosign_configure() saves them
for this machine. turbosign_whoami() shows which account this machine sends as.

THERE IS NO TEST SANDBOX. TurboSign has exactly one environment, and it is
production: api.turbodocx.com. Every turbosign_send emails a real person, is
recorded in a real audit trail, and cannot be recalled — only voided. There is
no test mode, no staging host, and no dry-run flag on the API itself.

So before the first send from any new machine, work up this ladder. Each rung
proves more than the last, and only the third one can reach a stranger:

  1. turbosign_whoami(verify=True) — proves the credentials work and the API is
     reachable from here. No document, no email, no quota used.
  2. turbosign_review(file_path, recipients) — the SAME code path as a send
     (upload, recipient parsing, field placement, server-side validation) but
     routed so that NO email goes out. Returns a preview URL: open it and check
     where the signature boxes actually landed. This is the rehearsal the API
     does not otherwise give you.
  3. turbosign_send(...) — to YOUR OWN address first. Only once you have seen
     that arrive should you send to anyone else.

Skipping to rung 3 on a new machine, a new document layout, or a new account is
how a half-placed signature box reaches a customer.

FOR HOSTS EMBEDDING THIS SERVER: put turbosign_send behind human approval, and
consider doing the same for turbosign_void (cancelling someone's pending
request is also irreversible). Leave turbosign_review ungated — it is the safe
rehearsal, and gating it removes the reason to prefer it.

RECOMMENDED WORKFLOW
1. turbosign_review(file_path, recipients, sender_email, sender_name) —
   prepares the document and returns a preview URL WITHOUT emailing anyone. Do
   this the first time you send a new kind of document, and look at where the
   signature boxes landed. It is held to every chain rule below, deliberately:
   a rehearsal that skipped the checks would not be a rehearsal.
2. turbosign_send(file_path, recipients, sender_email, sender_name) — the same
   call that actually emails the recipients. Keep the document_id it returns.
3. turbosign_status(document_id) — has anyone signed yet.
4. turbosign_download(document_id, output_path) — once complete, fetch the
   signed PDF.

Also: turbosign_void (cancel, reason required), turbosign_resend (chase a
recipient — get their id from turbosign_status), turbosign_audit_trail (who
opened it, and when).

THE SIGNING CHAIN MUST BE STATED, NEVER INFERRED. A signature request names
the parties to a legal instrument, so nothing about who signs is filled in for
you. Four rules, and a request that breaks any of them is refused before the
document is even read:

  1. NAMES ARE EXPLICIT. "Bob Smith <bob@example.com>" — a bare address is
     refused rather than given a name guessed from its local part. On an
     executed agreement that guess would be the name of a party.
  2. THE SENDER IS PER-SEND. sender_email and sender_name are required
     arguments on every review and send. There is no fallback to configuration.
  3. SIGNERS ARE ALLOWLISTED. TURBOSIGN_ALLOWED_SIGNERS, read from the
     environment only, so no tool call can widen it. Unset refuses everything
     rather than allowing everything. If you hit this, ask the human — you
     cannot fix it yourself, by design.
  4. THE DOCUMENT DECLARES THE CHAIN. Every document needs {Signature1}-style
     anchors, and they are cross-checked against the recipients.

PLACEMENT — THE DOCUMENT DECIDES, AND NOTHING ELSE CAN. The PDF must carry
inline text anchors where each party signs. There is no placement argument, no
coordinates, and no fields array: a PDF without anchors is refused, not guessed
at. This is narrower than the TurboSign API allows, on purpose — roughly ten
signatures landed in the wrong place on a real agreement before it was
hand-corrected, and every one was a position computed by something that could
not see the page.

HOW TO ANCHOR A DOCUMENT — get this right and the rest is easy:

__ANCHOR_GUIDANCE__

BEFORE CALLING review OR send, check the document for anchors. If it has a
signature block but no {Signature1} tokens, you must fix the SOURCE document
and re-export — anchors have to be real extractable text, so they cannot be
added to a finished PDF. There is no fallback to look for.

RECIPIENTS — "Bob Smith <bob@example.com>, Ann Jones <ann@example.com>". Every
recipient needs a name AND an address. By default everyone can sign at once;
pass sequential=true to make them sign in the order listed.

DATES — a date field renders in the SENDING ACCOUNT's configured format, and
the default is US-style: 08/01/2026 means 1 August 2026, which a day-first
reader will misread as 8 January. This is not settable per request and this
server cannot override it. Tell the human to change it once, in the TurboDocx
console under account settings, where unambiguous formats such as
"Saturday, August 1st, 2026" are available. Worth doing before anything goes
to a counterparty in another country. It is not retroactive — already-signed
documents keep the format they were signed with — so set it before sending,
not after.

Call get_instructions() to re-read this at any time.
"""

# The anchor layout is written once, in placement.py, and served from there —
# both in these instructions and in the error a document without anchors gets
# back. Two copies would drift, and the copy that drifted would be the one
# someone followed.
SERVER_INSTRUCTIONS = SERVER_INSTRUCTIONS.replace(
    "__ANCHOR_GUIDANCE__", ANCHOR_GUIDANCE
)

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
    """Run the MCP server over stdio, or handle a subcommand and exit."""
    argv = sys.argv[1:]

    if argv and argv[0] == "configure":
        # Terminal-driven credential entry: the key never enters an agent's
        # context or a conversation transcript. See cli.py.
        from .cli import run_configure

        raise SystemExit(run_configure(argv[1:]))
    # end if
    if "--selftest" in argv:
        raise SystemExit(_selftest())
    # end if
    if "--version" in argv:
        print(__version__)
        raise SystemExit(0)
    # end if

    mcp.run()
    return
# end def


if __name__ == "__main__":
    main()
# end if
