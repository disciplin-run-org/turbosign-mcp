"""Deciding where the signature boxes go.

Three strategies, and the default picks between the first two on its own:

* **anchor** — the document contains marker text like ``{Signature1}`` and
  TurboSign replaces it. Exact, and immune to any coordinate-system question.
* **coordinates** — boxes are placed geometrically on the last page. Works on
  any document, including one nobody prepared for signing.
* **explicit** — the caller supplies the fields array verbatim.

``auto`` reads the document, uses anchors when it finds them, and falls back to
geometry when it does not. So a prepared template gets exact placement for free
and an arbitrary PDF still just works.
"""

from __future__ import annotations

import io
import re

from .errors import TurboSignError

# ---------------------------------------------------------------------------
# Coordinate system
# ---------------------------------------------------------------------------
# Top-left origin: `y` is the distance DOWN from the top edge of the page.
#
# Documented — "Vertical position from top edge (pixels)" — though not on the
# TurboSign API page that covers everything else about fields, which is why
# this was initially treated as an open question and verified empirically
# instead. It was: a review of an unanchored PDF put the boxes at the foot of
# the last page, matching. Documentation and behaviour agree.
#
# The docs say "pixels" while we send PDF points from pypdf's mediabox. That
# discrepancy is moot because build_coordinate_fields also sends pageWidth and
# pageHeight, so the server scales into whatever units it uses.
#
# Kept as one constant so a future API change stays a one-line fix.
# Record in docs/VERIFICATION.md.
Y_ORIGIN = "top"

# Page geometry for the coordinate fallback, in PDF points (72 per inch).
BOTTOM_MARGIN = 54.0
LEFT_MARGIN = 54.0
ROW_GAP = 18.0

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

# Field types placed automatically for each recipient when no anchors exist.
DEFAULT_AUTO_FIELDS: tuple[str, ...] = ("signature", "date")


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


def page_geometry(content: bytes) -> tuple[int, float, float]:
    """Return ``(page_count, width, height)`` of the document's last page."""
    reader = read_pdf(content)
    count = len(reader.pages)
    if count == 0:
        raise TurboSignError(
            "That PDF has no pages.",
            "Check the document was exported correctly.",
        )
    # end if
    box = reader.pages[-1].mediabox
    return count, float(box.width), float(box.height)
# end def


def _y_for(page_height: float, box_height: float, from_bottom: float) -> float:
    """Convert a distance up from the page bottom into an API ``y``.

    The single place the coordinate-origin assumption is applied.
    """
    if Y_ORIGIN == "top":
        return max(0.0, page_height - from_bottom - box_height)
    # end if
    return max(0.0, from_bottom)
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


def build_coordinate_fields(
    content: bytes,
    recipients: list[dict],
    field_types: tuple[str, ...] = DEFAULT_AUTO_FIELDS,
) -> list[dict]:
    """Place a row of fields per recipient at the foot of the last page.

    Rows stack upward from the bottom margin so the first recipient is lowest,
    which reads the way a signature block on paper does.
    """
    page_count, page_width, page_height = page_geometry(content)

    row_height = max(_size_for(t)[1] for t in field_types)
    rows_needed = len(recipients)
    total_height = rows_needed * row_height + max(0, rows_needed - 1) * ROW_GAP
    if BOTTOM_MARGIN + total_height > page_height:
        raise TurboSignError(
            f"{len(recipients)} signature blocks do not fit on the last page.",
            "Send to fewer recipients at a time, or add {Signature1}-style "
            "anchors to the document and let TurboSign place them.",
        )
    # end if

    fields: list[dict] = []
    for row, recipient in enumerate(recipients):
        from_bottom = BOTTOM_MARGIN + row * (row_height + ROW_GAP)
        x = LEFT_MARGIN
        for field_type in field_types:
            width, height = _size_for(field_type)
            if x + width > page_width - LEFT_MARGIN:
                # Ran out of horizontal room; drop this one rather than
                # send coordinates the API will reject.
                continue
            # end if
            fields.append(
                {
                    "recipientEmail": recipient["email"],
                    "type": field_type,
                    "required": True,
                    "page": page_count,
                    "x": round(x, 2),
                    "y": round(_y_for(page_height, height, from_bottom), 2),
                    "width": width,
                    "height": height,
                    "pageWidth": round(page_width, 2),
                    "pageHeight": round(page_height, 2),
                }
            )
            x += width + ROW_GAP
        # end for
    # end for
    return fields
# end def


def resolve_fields(
    content: bytes,
    filename: str,
    recipients: list[dict],
    placement: str = "auto",
    fields=None,
    anchor: str | None = None,
) -> tuple[list[dict], str]:
    """Work out the fields array for a send.

    Returns:
        ``(fields, strategy)`` where strategy is one of ``"explicit"``,
        ``"anchor"`` or ``"coordinates"`` — reported back to the caller so it
        is always visible which way a document was handled.
    """
    if fields:
        parsed = fields
        if isinstance(fields, str):
            import json

            try:
                parsed = json.loads(fields)
            except ValueError as exc:
                raise TurboSignError(
                    f"fields was a string but would not parse as JSON: {exc}",
                    "Pass a JSON array, or omit fields and let placement=auto "
                    "handle it.",
                ) from exc
            # end try
        # end if
        if not isinstance(parsed, list) or not parsed:
            raise TurboSignError(
                "fields must be a non-empty array.",
                "Omit it entirely to use automatic placement.",
            )
        # end if
        return parsed, "explicit"
    # end if

    if placement not in {"auto", "anchor", "coordinates", "explicit"}:
        raise TurboSignError(
            f"Unknown placement {placement!r}.",
            "Use auto, anchor, coordinates, or explicit.",
        )
    # end if

    if placement == "explicit":
        raise TurboSignError(
            "placement='explicit' needs a fields array.",
            "Pass fields, or use placement='auto'.",
        )
    # end if

    if anchor:
        # A single named anchor, one per recipient in order.
        built = build_anchor_fields([anchor], recipients)
        if not built:
            raise TurboSignError(
                f"{anchor!r} is not a recognised anchor token.",
                "Use a token like {Signature1}, {Date1} or {Initial1}.",
            )
        # end if
        return built, "anchor"
    # end if

    if not is_pdf(filename):
        raise TurboSignError(
            f"Automatic placement can only read PDFs, and this is {filename}.",
            "Either convert the document to PDF, or pass an anchor / explicit "
            "fields so nothing has to be measured.",
        )
    # end if

    tokens = find_anchors(content)

    if placement == "anchor":
        if not tokens:
            raise TurboSignError(
                "placement='anchor' was requested but the document contains "
                "no anchor tokens.",
                "Add text like {Signature1} where the box should go, or use "
                "placement='auto' to fall back to automatic positioning.",
            )
        # end if
        return build_anchor_fields(tokens, recipients), "anchor"
    # end if

    if placement == "auto" and tokens:
        return build_anchor_fields(tokens, recipients), "anchor"
    # end if

    return build_coordinate_fields(content, recipients), "coordinates"
# end def
