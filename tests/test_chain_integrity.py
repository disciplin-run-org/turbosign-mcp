"""The signing chain must be stated, never inferred.

A signature request names the parties to a legal instrument. Every convenience
that lets one of those names arrive by default rather than by decision is a way
for the wrong person to end up on a contract without anyone choosing it — and on
an agent-driven box, "nobody chose it" includes "the model chose it".

So the initiator states the whole chain, and the server refuses anything less.
Four rules, each closing a different hole:

  1. NAMES ARE EXPLICIT.  No display name is invented from an address, and the
     sender is not inherited from config.
  2. SIGNERS ARE PERMITTED.  Addresses must match an allowlist held in the
     environment, which is out of reach of a tool call.
  3. THE DOCUMENT DECLARES THE CHAIN.  Anchors are cross-checked against the
     recipients, so a party cannot be added to or dropped from a contract whose
     signature blocks say otherwise.
  4. THERE IS NO UNANCHORED PATH.  Geometry placement is gone; a document that
     declares nothing cannot be sent.

Rules 1 and 2 are about who; 3 and 4 are about the document agreeing.
"""

from __future__ import annotations

import pytest

from turbosign_mcp import chain
from turbosign_mcp.errors import TurboSignError
from turbosign_mcp.recipients import parse_recipients


# ── 1. names are explicit ────────────────────────────────────────────────────

def test_a_bare_address_is_refused_rather_than_named_for_you():
    """`ann.jones@example.com` used to become "Ann Jones".

    Nobody decided that. It is a guess from an email local part, and on an
    executed agreement it is the name of a party.
    """
    with pytest.raises(TurboSignError) as exc:
        parse_recipients("ann.jones@example.com")
    assert "name" in str(exc.value).lower()


def test_a_named_address_is_still_fine():
    """Positive control: the rule rejects anonymity, not addresses."""
    assert parse_recipients("Ann Jones <ann.jones@example.com>") == [
        {"name": "Ann Jones", "email": "ann.jones@example.com", "signingOrder": 1}
    ]


def test_one_unnamed_party_in_a_list_fails_the_whole_list():
    """Partial naming is the dangerous case — it looks careful."""
    with pytest.raises(TurboSignError):
        parse_recipients("Bob Smith <bob@example.com>, ann@example.com")


def test_a_json_recipient_without_a_name_is_refused():
    with pytest.raises(TurboSignError):
        parse_recipients('[{"email": "ann@example.com"}]')


def test_sender_must_be_supplied_by_the_caller():
    for email, name in (("", "Jesper"), ("j@x.com", ""), ("", "")):
        with pytest.raises(TurboSignError):
            chain.require_sender(email, name)


def test_a_complete_sender_passes():
    chain.require_sender("jesper@example.com", "Jesper Jurcenoks")


# ── 2. signers are permitted ─────────────────────────────────────────────────

def test_an_unset_allowlist_refuses_everything():
    """Fail closed. An empty allowlist is not "allow all" — it is unconfigured.

    Reading absence as permission is how the Signal gateway nearly became a
    command channel; the same mistake is not made twice.
    """
    people = parse_recipients("Bob Smith <bob@example.com>")
    with pytest.raises(TurboSignError) as exc:
        chain.require_allowed_signers(people, allowlist=[])
    assert "allowlist" in str(exc.value).lower()


def test_an_exact_address_is_allowed():
    people = parse_recipients("Bob Smith <bob@acme.com>")
    chain.require_allowed_signers(people, allowlist=["bob@acme.com"])


def test_a_domain_entry_allows_its_members():
    people = parse_recipients("Bob Smith <bob@acme.com>")
    chain.require_allowed_signers(people, allowlist=["@acme.com"])


def test_a_lookalike_domain_is_refused():
    """The case the naming rule cannot see: a well-formed, fully named stranger."""
    people = parse_recipients("Bob Smith <bob@acme-invoices.com>")
    with pytest.raises(TurboSignError) as exc:
        chain.require_allowed_signers(people, allowlist=["@acme.com"])
    assert "acme-invoices.com" in str(exc.value)


def test_matching_is_case_insensitive():
    people = parse_recipients("Bob Smith <Bob@ACME.com>")
    chain.require_allowed_signers(people, allowlist=["@acme.com"])


def test_one_disallowed_signer_fails_the_whole_chain():
    people = parse_recipients("Bob <bob@acme.com>, Mallory <m@evil.com>")
    with pytest.raises(TurboSignError):
        chain.require_allowed_signers(people, allowlist=["@acme.com"])


def test_allowlist_parsing_ignores_blanks_and_case():
    assert chain.parse_allowlist(" @Acme.com , bob@Example.COM ,, ") == [
        "@acme.com", "bob@example.com"
    ]


# ── 3. the document declares the chain ───────────────────────────────────────

def test_every_recipient_must_have_an_anchor():
    """A third party on a two-signature contract gets no field at all.

    build_anchor_fields already refuses MORE anchors than recipients. This is
    the reverse, and it is the one an agent could produce by adding a name.
    """
    people = parse_recipients("A <a@x.com>, B <b@x.com>, C <c@x.com>")
    with pytest.raises(TurboSignError) as exc:
        chain.require_anchor_coverage(["{Signature1}", "{Signature2}"], people)
    assert "3" in str(exc.value)


def test_full_coverage_passes():
    people = parse_recipients("A <a@x.com>, B <b@x.com>")
    chain.require_anchor_coverage(["{Signature1}", "{Date1}", "{Signature2}"], people)


def test_an_undigited_anchor_covers_the_first_recipient():
    """{Signature} with no digit means recipient one — the existing convention."""
    people = parse_recipients("A <a@x.com>")
    chain.require_anchor_coverage(["{Signature}"], people)


def test_a_document_with_no_anchors_declares_nothing():
    people = parse_recipients("A <a@x.com>")
    with pytest.raises(TurboSignError):
        chain.require_anchor_coverage([], people)
