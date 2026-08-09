"""Turning what a human says into the recipient array TurboSign wants.

The whole point of the server is that "send this to Bob Smith
<bob@example.com>" should work. That is a parsing problem, not a judgement
problem, so it is solved with a parser rather than a model call.
"""

from __future__ import annotations

import json
import re

from .errors import TurboSignError

# "Bob Smith <bob@example.com>" or "<bob@example.com>" or "bob@example.com"
_NAMED = re.compile(r"^\s*(?P<name>[^<>]*?)\s*<\s*(?P<email>[^<>\s]+)\s*>\s*$")

# Deliberately permissive. The API is the authority on what address it will
# accept; this only catches input that is obviously not an address at all.
_EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")

# One recipient inside a list. Splitting a recipient string on commas does not
# work — "Smith, Bob <bob@example.com>" is one person, not two — so the list is
# tokenised by finding the addresses instead, and whatever precedes an address
# is its display name. Excluding "@" from the name part is what stops a bare
# address being swallowed into the previous recipient's name.
_UNIT = re.compile(
    r"(?P<name>[^<>@]*)<\s*(?P<email>[^<>\s]+)\s*>"
    r"|(?P<bare>[^\s,;<>]+@[^\s,;<>]+)"
)


def _require_name(email: str) -> str:
    """Refuse an unnamed party. Never invent one.

    This used to derive a display name from the address — "ann.jones@x.com"
    became "Ann Jones". Nobody decided that, and on an executed agreement it is
    the name of a party to a contract. A guess from a local part is not a
    signatory.
    """
    raise TurboSignError(
        f"{email} was given without a name.",
        'Every party must be named by the initiator: use '
        '"Ann Jones <ann.jones@example.com>", or a JSON array of '
        '{"name", "email"} objects. Names are no longer derived from the '
        "address.",
    )
# end def


def _parse_string(text: str) -> list[tuple[str, str]]:
    """Parse a recipient string into ``(name, email)`` pairs.

    Works by locating the addresses rather than splitting on commas, so a
    display name containing a comma survives intact.
    """
    people: list[tuple[str, str]] = []
    for match in _UNIT.finditer(text):
        bare = match.group("bare")
        if bare:
            if not _EMAIL.match(bare):
                raise TurboSignError(
                    f"{bare!r} does not look like an email address.",
                    'Use the form "Bob Smith <bob@example.com>".',
                )
            # end if
            people.append((_require_name(bare), bare))
            continue
        # end if

        email = (match.group("email") or "").strip()
        if not _EMAIL.match(email):
            raise TurboSignError(
                f"{email!r} does not look like an email address.",
                'Use the form "Bob Smith <bob@example.com>".',
            )
        # end if
        # Strip the separator left over from the preceding recipient.
        name = (match.group("name") or "").strip().strip(",;").strip().strip('"').strip()
        people.append((name or _require_name(email), email))
    # end for

    if not people:
        raise TurboSignError(
            f"Could not read {text!r} as a recipient list.",
            'Use "Bob Smith <bob@example.com>", a bare address, or a JSON array '
            'of {"name", "email"} objects.',
        )
    # end if
    return people
# end def


def _parse_one(chunk: str) -> tuple[str, str]:
    """Parse a single recipient into ``(name, email)``."""
    match = _NAMED.match(chunk)
    if match:
        email = match.group("email").strip()
        name = match.group("name").strip().strip('"').strip()
        if not _EMAIL.match(email):
            raise TurboSignError(
                f"{email!r} does not look like an email address.",
                'Use the form "Bob Smith <bob@example.com>".',
            )
        # end if
        return (name or _require_name(email)), email
    # end if

    bare = chunk.strip().strip('"')
    if _EMAIL.match(bare):
        return _require_name(bare), bare
    # end if

    raise TurboSignError(
        f"Could not read {chunk!r} as a recipient.",
        'Use "Bob Smith <bob@example.com>", a bare address, or a JSON array '
        'of {"name", "email"} objects.',
    )
# end def


def parse_recipients(value, sequential: bool = False) -> list[dict]:
    """Normalise recipients into TurboSign's array shape.

    Accepts a display string ("Bob Smith <bob@x.com>, ann@y.com"), a JSON
    string holding an array, or an already-structured list of dicts.

    Args:
        value: What the caller supplied.
        sequential: When true, recipients are numbered 1..N and must sign in
            that order. When false — the default — everyone gets
            ``signingOrder: 1`` and can sign in parallel.

    Returns:
        A list of ``{"name", "email", "signingOrder"}`` dicts.

    Raises:
        TurboSignError: On unparseable input, no recipients, or a duplicate
            address (the API requires them to be unique).
    """
    people: list[tuple[str, str]] = []

    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise TurboSignError(
                "No recipients were given.",
                'Pass recipients, for example "Bob Smith <bob@example.com>".',
            )
        # end if
        if text.startswith("["):
            try:
                value = json.loads(text)
            except ValueError as exc:
                raise TurboSignError(
                    f"recipients looked like JSON but would not parse: {exc}",
                    'Either pass valid JSON or use the plain form '
                    '"Bob Smith <bob@example.com>".',
                ) from exc
            # end try
        else:
            people = _parse_string(text)
        # end if
    # end if

    if isinstance(value, dict):
        value = [value]
    # end if

    explicit_orders: dict[str, int] = {}
    if isinstance(value, list):
        for entry in value:
            if isinstance(entry, str):
                people.append(_parse_one(entry))
                continue
            # end if
            if not isinstance(entry, dict):
                raise TurboSignError(
                    f"Recipient entry {entry!r} is not an object.",
                    'Each entry needs at least an "email" key.',
                )
            # end if
            email = str(entry.get("email", "")).strip()
            if not _EMAIL.match(email):
                raise TurboSignError(
                    f"Recipient {entry!r} has no usable email address.",
                    'Every recipient needs an "email".',
                )
            # end if
            name = str(entry.get("name") or "").strip() or _require_name(email)
            people.append((name, email))
            order = entry.get("signingOrder")
            if isinstance(order, int) and order >= 1:
                explicit_orders[email.lower()] = order
            # end if
        # end for
    # end if

    if not people:
        raise TurboSignError(
            "No recipients were given.",
            'Pass recipients, for example "Bob Smith <bob@example.com>".',
        )
    # end if

    seen: set[str] = set()
    out: list[dict] = []
    for index, (name, email) in enumerate(people, start=1):
        key = email.lower()
        if key in seen:
            raise TurboSignError(
                f"{email} appears twice in the recipient list.",
                "TurboSign requires each recipient address to be unique.",
            )
        # end if
        seen.add(key)
        out.append(
            {
                "name": name,
                "email": email,
                "signingOrder": explicit_orders.get(key, index if sequential else 1),
            }
        )
    # end for
    return out
# end def
