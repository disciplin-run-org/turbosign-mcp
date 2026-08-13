"""Where the signature boxes go: inline text anchors, and nothing else.

The document says where each party signs, by carrying marker text like
``{Signature1}`` at the place the signature belongs. There is one mechanism and
no alternative — no geometric placement, no caller-supplied coordinates.

That is a deliberate narrowing of what the TurboSign API itself allows, and it
was bought with experience: roughly ten separate attempts placed a signature in
the wrong place on a real agreement before the document was hand-corrected.
Every one of those was a position computed by something that could not see the
page. An anchor cannot be off by a page or a hundred points, because the author
put it where the signature goes.

The cost is real and accepted: a PDF you cannot edit cannot be sent through
this server. Add the anchors to the source and re-export.

See ``ANCHOR_GUIDANCE`` for the layout that works, which is also served to
callers through the MCP instructions.
"""

from __future__ import annotations

import io
import re

from .errors import TurboSignError

# Default box sizes per field type.
FIELD_SIZES: dict[str, tuple[float, float]] = {
    "signature": (200.0, 60.0),
    "initial": (60.0, 40.0),
    "date": (120.0, 40.0),
    "full_name": (180.0, 40.0),
    "first_name": (140.0, 40.0),
    "last_name": (140.0, 40.0),
    "title": (180.0, 40.0),
    "company": (180.0, 40.0),
    "email": (200.0, 40.0),
    "text": (180.0, 40.0),
    "checkbox": (24.0, 24.0),
}

# Anchor tokens: {Signature1}, {date 2}, {initials}, ... The trailing digit is
# the recipient's signing position; absent means the first recipient.
ANCHOR_RE = re.compile(
    r"\{\s*(?P<kind>signature|sig|initials|initial|date|full_?name|name|"
    r"first_?name|last_?name|title|company|email|text|checkbox)"
    r"\s*(?P<index>\d*)\s*\}",
    re.IGNORECASE,
)

_KIND_TO_TYPE: dict[str, str] = {
    "signature": "signature",
    "sig": "signature",
    "initial": "initial",
    "initials": "initial",
    "date": "date",
    "fullname": "full_name",
    "full_name": "full_name",
    "name": "full_name",
    "firstname": "first_name",
    "first_name": "first_name",
    "lastname": "last_name",
    "last_name": "last_name",
    "title": "title",
    "company": "company",
    "email": "email",
    "text": "text",
    "checkbox": "checkbox",
}

# How to lay the anchors out. Served to callers verbatim through the MCP
# instructions, because an agent preparing a document is exactly who needs it
# and exactly who will otherwise guess.
ANCHOR_GUIDANCE = """\
Put the anchors in the SOURCE document, then export the PDF. They have to be
real extractable text, so they cannot be added to a finished PDF.

Layout, per signing party:

     {Signature1}<tab><tab>{Date1}
     ______________________________________________
     [Ann Jones Signature & Date]

Four rules that matter:

  1. ABOVE THE LINE. The anchor goes on its own line directly above the
     signature rule, not on it and not below it. TurboSign draws the field
     downward from where the anchor sits, so an anchor above the rule puts the
     signature ON the rule. An anchor on the rule pushes it below.
  2. INVISIBLE. Set the anchor text to the page background colour — white on
     white. It is still real text, so TurboSign finds it, but nobody sees
     {Signature1} on the executed agreement.
  3. SIGNATURE LEFT, DATE RIGHT. Both on that same line, separated by tabs.
  4. THE NUMBER IS THE SIGNER'S POSITION IN YOUR RECIPIENTS LIST, not the
     order they appear in the document. If the company counter-signs at the
     top of the page but is second in your recipients list, the company's
     anchors are {Signature2}/{Date2}. Getting this backwards swaps who signs
     where, and the document will still send.

Label the line underneath — "[Company Signature & Date]" — so a human reading
the draft can see whose block is whose before anyone signs."""


def _size_for(field_type: str) -> tuple[float, float]:
    """Default width and height for a field type."""
    return FIELD_SIZES.get(field_type, (180.0, 40.0))
# end def


def is_pdf(filename: str) -> bool:
    """Whether this filename is one pypdf can read."""
    return filename.lower().endswith(".pdf")
# end def


def read_pdf(content: bytes):
    """Open a PDF, raising an agent-readable error if it will not open."""
    try:
        from pypdf import PdfReader

        return PdfReader(io.BytesIO(content))
    except Exception as exc:  # pypdf raises a wide variety on damaged files
        raise TurboSignError(
            f"That file could not be read as a PDF: {exc}",
            "Check the file opens in a normal PDF viewer. If it is encrypted, "
            "remove the password first.",
        ) from exc
    # end try


def extract_text(content: bytes) -> str:
    """Extract all text from a PDF, or an empty string if there is none.

    A scanned document has no text layer, and that is not an error — it just
    means there are no anchors and geometry will be used instead.
    """
    reader = read_pdf(content)
    parts: list[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue  # one unreadable page must not lose the others
        # end try
    # end for
    return "\n".join(parts)
# end def


def find_anchors(content: bytes) -> list[str]:
    """Return the anchor tokens present in a PDF, in document order."""
    seen: list[str] = []
    for match in ANCHOR_RE.finditer(extract_text(content)):
        token = match.group(0)
        if token not in seen:
            seen.append(token)
        # end if
    # end for
    return seen
# end def


def build_anchor_fields(tokens: list[str], recipients: list[dict]) -> list[dict]:
    """Build template/anchor fields from the tokens found in a document.

    The trailing digit on a token selects the recipient — ``{Signature2}``
    belongs to the second recipient. A token with no digit goes to the first.
    """
    fields: list[dict] = []
    for token in tokens:
        match = ANCHOR_RE.match(token)
        if not match:
            continue
        # end if
        kind = match.group("kind").lower().replace("_", "")
        field_type = _KIND_TO_TYPE.get(kind) or _KIND_TO_TYPE.get(
            match.group("kind").lower(), "text"
        )
        index = int(match.group("index") or 1)
        if index > len(recipients):
            raise TurboSignError(
                f"The document contains {token} but only "
                f"{len(recipients)} recipient(s) were given.",
                "Add the missing recipient, or edit the document to remove "
                "that anchor.",
            )
        # end if
        width, height = _size_for(field_type)
        fields.append(
            {
                "recipientEmail": recipients[index - 1]["email"],
                "type": field_type,
                "required": True,
                "template": {
                    "anchor": token,
                    "placement": "replace",
                    "size": {"width": width, "height": height},
                    "caseSensitive": False,
                },
            }
        )
    # end for
    return fields
# end def


# Phrases that say the document already carries its own signature block.
# Deliberately narrow — a long underscore run or an explicit "Signature:" is
# somewhere a human expects a signature to land. "Date:" alone is not here; it
# is far too common in ordinary prose to mean anything.
SIGNATURE_HINT_RE = re.compile(
    r"(signature\s*:|signed\s*:|sign\s+here|signature\s+of\b|_{6,}|\.{10,})",
    re.IGNORECASE,
)


def find_signature_hints(content: bytes, limit: int = 4) -> list[str]:
    """Phrases suggesting the document has a signature block of its own.

    Used to make the no-anchors refusal specific: a document that already
    prints "Signature: ______" has somewhere obvious for the anchors to go,
    and saying so beats repeating generic instructions. Detection is a regex,
    not a judgement — it reports what it saw.
    """
    try:
        text = extract_text(content)
    except TurboSignError:
        return []
    # end try

    seen: list[str] = []
    for match in SIGNATURE_HINT_RE.finditer(text):
        phrase = " ".join(match.group(0).split())
        if len(phrase) > 20:
            phrase = phrase[:20] + "..."
        # end if
        if phrase.lower() not in {s.lower() for s in seen}:
            seen.append(phrase)
        # end if
        if len(seen) >= limit:
            break
        # end if
    # end for
    return seen
# end def


def resolve_fields(
    content: bytes,
    filename: str,
    recipients: list[dict],
) -> tuple[list[dict], str]:
    """Build the fields array from the anchors in the document.

    Inline text anchors are the only mechanism. There is no placement
    parameter and no caller-supplied fields array, because every placement this
    server has ever got wrong was a position computed by something that could
    not see the page.

    Returns:
        ``(fields, "anchor")``. The strategy is returned for a caller that logs
        it, and is always "anchor".

    Raises:
        TurboSignError: If the file is not a PDF, carries no anchors, or its
            anchors do not account for every recipient.
    """
    if not is_pdf(filename):
        raise TurboSignError(
            f"Signature anchors can only be read from a PDF, and this is "
            f"{filename}.",
            "Export the document to PDF with the anchors already in it.",
        )
    # end if

    tokens = find_anchors(content)
    if not tokens:
        hint = ANCHOR_GUIDANCE
        blocks = find_signature_hints(content)
        if blocks:
            hint = (
                "This document does have a signature block — found "
                + ", ".join(repr(b) for b in blocks)
                + ". Put the anchors there.\n\n"
                + hint
            )
        # end if
        raise TurboSignError(
            "The document carries no signature anchors, so it does not say "
            "where anyone signs.",
            hint,
        )
    # end if

    fields = build_anchor_fields(tokens, recipients)

    # Every recipient must have somewhere to sign. A document whose anchors
    # cover only some of the signers would send, and the omitted party would
    # receive an agreement with no field to complete.
    covered = {f["recipientEmail"] for f in fields}
    missing = [r["email"] for r in recipients if r["email"] not in covered]
    if missing:
        raise TurboSignError(
            "The document has no anchors for: " + ", ".join(missing) + ".",
            "Every recipient needs their own numbered anchors. Recipient N in "
            "your list signs at {SignatureN}/{DateN} — the number is their "
            "position in the recipients list, not their position in the "
            "document.\n\n" + ANCHOR_GUIDANCE,
        )
    # end if

    return fields, "anchor"
# end def
