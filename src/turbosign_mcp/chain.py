"""Rules about who is in a signing chain.

A signature request names the parties to a legal instrument. Every convenience
that lets one of those names arrive by default rather than by decision is a way
for the wrong person to end up on a contract without anyone choosing it — and
where an agent drives this server, "nobody chose it" includes "the model chose
it".

So the initiator states the whole chain and this module refuses anything less.
The functions here are pure and take their inputs explicitly, so each rule can
be tested on its own rather than only through a send.

The rules and what each one catches:

    require_sender            reply-to inherited from config
    require_anchor_coverage   a party added to, or dropped from, a contract
                              whose signature blocks say otherwise
    (and in placement.py)     a document that declares nothing at all

There was a fourth: a signer allowlist, read from the environment, which
refused any recipient outside it. It is gone, and the reasoning is worth
keeping because it will be proposed again.

The argument for it was prompt injection — bounding who a manipulated agent
could send a binding document to. The argument against it, which won: if you
send someone a document TO SIGN, sending it is what permission means. The
allowlist demanded that every counterparty be pre-approved in an environment
variable before the one thing this server exists to do could happen, so
signing an agreement with anybody new became an operator task on the box.
That is a large, permanent, everyday cost against an occasional threat that
is already covered where it matters: on an agent deployment, turbosign_send
sits behind human approval, and the human approving it is the person who
decided to send.

See AR-7.
"""

from __future__ import annotations

import re

from .errors import TurboSignError

# Same token grammar placement.py uses to assign fields, imported rather than
# restated: two regexes that must agree is a bug waiting for a quiet afternoon.
from .placement import ANCHOR_RE


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
