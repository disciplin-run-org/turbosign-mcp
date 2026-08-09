"""Rules about who is in a signing chain.

A signature request names the parties to a legal instrument. Every convenience
that lets one of those names arrive by default rather than by decision is a way
for the wrong person to end up on a contract without anyone choosing it — and
where an agent drives this server, "nobody chose it" includes "the model chose
it".

So the initiator states the whole chain and this module refuses anything less.
The functions here are pure and take their inputs explicitly, so each rule can
be tested on its own rather than only through a send.

The four rules and what each one catches:

    require_sender            reply-to inherited from config
    require_allowed_signers   a fully named stranger at a lookalike domain
    require_anchor_coverage   a party added to, or dropped from, a contract
                              whose signature blocks say otherwise
    (and in placement.py)     a document that declares nothing at all

They are complementary, not alternatives. A well-formed name passes rule 1 and
tells you nothing about whether that person belongs on the agreement; the
document's own anchors are the only declaration in the request that the caller
did not write at the moment of sending.
"""

from __future__ import annotations

import os
import re

from .errors import TurboSignError

# Same token grammar placement.py uses to assign fields, imported rather than
# restated: two regexes that must agree is a bug waiting for a quiet afternoon.
from .placement import ANCHOR_RE

ALLOWLIST_ENV = "TURBOSIGN_ALLOWED_SIGNERS"


def parse_allowlist(raw: str | None) -> list[str]:
    """Split the allowlist env var into normalised entries.

    Entries are either a full address (``bob@acme.com``) or a domain
    (``@acme.com``). Case is folded because addresses are not case sensitive in
    any way that should decide who may sign a contract.
    """
    if not raw:
        return []
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def load_allowlist() -> list[str]:
    """The configured allowlist, from the environment only.

    Environment rather than the credential store on purpose: on an agent box the
    store is a file the agent can write, and an allowlist a tool call can edit
    is not an allowlist. See the store/env split in credentials.py.
    """
    return parse_allowlist(os.environ.get(ALLOWLIST_ENV))


def require_sender(sender_email: str, sender_name: str) -> None:
    """Both halves of the sender must be stated by the caller.

    There is deliberately no fallback to the configured sender. The reply-to on
    a signature request is where a counterparty's "I do not agree to clause 4"
    lands, and it should be a decision made per send, visible in the call, not a
    value inherited from a config file written months earlier.
    """
    missing = [
        label
        for label, value in (("sender_email", sender_email), ("sender_name", sender_name))
        if not (value or "").strip()
    ]
    if missing:
        raise TurboSignError(
            f"The sender must be stated on every request; missing: {', '.join(missing)}.",
            'Pass sender_email="you@example.com" and sender_name="Your Name". '
            "They are no longer taken from configuration — the sender of a "
            "signature request is a per-send decision.",
        )


def require_allowed_signers(recipients: list[dict], allowlist: list[str] | None = None) -> None:
    """Every signer must match the configured allowlist.

    An EMPTY allowlist refuses everything rather than allowing everything. That
    direction is not arbitrary: reading absence as permission is the exact shape
    that turns a messaging gateway into a command channel, and it costs nothing
    to be explicit here.
    """
    entries = load_allowlist() if allowlist is None else allowlist
    if not entries:
        raise TurboSignError(
            f"No signer allowlist is configured, so no signer can be approved.",
            f"Set {ALLOWLIST_ENV} to the addresses or domains permitted to "
            'sign, e.g. "@yourcompany.com, counsel@example.com". It is read '
            "from the environment only, so a tool call cannot widen it.",
        )

    rejected = []
    for person in recipients:
        email = (person.get("email") or "").strip().lower()
        domain = "@" + email.partition("@")[2]
        if email not in entries and domain not in entries:
            rejected.append(person.get("email") or "(no address)")

    if rejected:
        raise TurboSignError(
            "These signers are not on the allowlist: " + ", ".join(rejected) + ".",
            f"Add them to {ALLOWLIST_ENV}, or correct the address. A name that "
            "reads correctly is not evidence that the address does — this is "
            "the check that sees a lookalike domain.",
        )


def anchor_indices(tokens: list[str]) -> set[int]:
    """Recipient positions the document's anchors actually cover.

    A token with no trailing digit belongs to the first recipient, matching
    build_anchor_fields.
    """
    covered: set[int] = set()
    for token in tokens:
        match = ANCHOR_RE.match(token)
        if not match:
            continue
        covered.add(int(match.group("index") or 1))
    return covered


def require_anchor_coverage(tokens: list[str], recipients: list[dict]) -> None:
    """The document must have a field for every recipient.

    build_anchor_fields already refuses MORE anchors than recipients — a
    document expecting a third signatory who was not supplied. This is the
    reverse and the more dangerous direction: an extra recipient on a contract
    whose signature blocks do not mention them would otherwise be sent, receive
    the email, and simply have nothing to sign.

    It is also the only rule here whose declaration the caller did not author at
    send time. The anchors are in the document a human drafted.
    """
    if not tokens:
        raise TurboSignError(
            "The document contains no signature anchors, so it does not say who "
            "signs it.",
            "Add tokens like {Signature1} and {Date1} where each party signs. "
            "Automatic placement by geometry was removed: a document that "
            "declares nothing cannot be checked against the recipients.",
        )

    covered = anchor_indices(tokens)
    uncovered = [i for i in range(1, len(recipients) + 1) if i not in covered]
    if uncovered:
        names = ", ".join(
            f"#{i} {recipients[i - 1].get('name')} <{recipients[i - 1].get('email')}>"
            for i in uncovered
        )
        raise TurboSignError(
            f"{len(recipients)} recipient(s) were given, but the document has no "
            f"anchor for: {names}.",
            "Either the recipient does not belong on this document, or the "
            "document is missing their signature block. Both are worth looking "
            "at before anyone is emailed.",
        )
