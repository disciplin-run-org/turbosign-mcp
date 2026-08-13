"""Placement: inline text anchors, and nothing else.

There is no geometry and no caller-supplied coordinates. Every placement this
server got wrong in practice was a position computed by something that could
not see the page, so the document is now the only thing that decides.
"""

from __future__ import annotations

import pytest

from turbosign_mcp.errors import TurboSignError
from turbosign_mcp.placement import (
    ANCHOR_GUIDANCE,
    build_anchor_fields,
    find_anchors,
    find_signature_hints,
    resolve_fields,
)

from .conftest import make_pdf


# -- anchor detection ------------------------------------------------------


def test_anchors_are_found_in_document_order(anchored_pdf):
    assert find_anchors(anchored_pdf) == ["{Signature1}", "{Date1}", "{Signature2}"]
# end def


def test_a_document_without_anchors_reports_none(plain_pdf):
    assert find_anchors(plain_pdf) == []
# end def


def test_anchor_matching_is_case_insensitive():
    assert find_anchors(make_pdf("{signature1} {SIG2}")) == ["{signature1}", "{SIG2}"]
# end def


# -- anchors are the only mechanism ---------------------------------------


def test_anchors_place_the_fields(anchored_pdf, two_recipients):
    fields, strategy = resolve_fields(anchored_pdf, "a.pdf", two_recipients)
    assert strategy == "anchor"
    assert all("template" in f for f in fields), "every field must be anchor-bound"
    assert not any("x" in f or "y" in f for f in fields), "no coordinates anywhere"
# end def


def test_the_anchor_number_selects_the_recipient(anchored_pdf, two_recipients):
    # The number is the signer's position in the recipients list. In a real
    # agreement the counter-signing party often appears FIRST on the page, so
    # document order and signer order routinely disagree.
    fields, _ = resolve_fields(anchored_pdf, "a.pdf", two_recipients)
    by_anchor = {f["template"]["anchor"]: f["recipientEmail"] for f in fields}
    assert by_anchor["{Signature1}"] == "bob@example.com"
    assert by_anchor["{Signature2}"] == "ann@example.com"
# end def


def test_anchor_kind_maps_to_field_type(anchored_pdf, two_recipients):
    fields, _ = resolve_fields(anchored_pdf, "a.pdf", two_recipients)
    types = {f["template"]["anchor"]: f["type"] for f in fields}
    assert types["{Signature1}"] == "signature"
    assert types["{Date1}"] == "date"
# end def


def test_resolve_fields_takes_no_placement_or_fields_argument():
    # The narrowing is the point: if these come back, geometry comes back with
    # them. build_coordinate_fields was reachable through fields= before.
    import inspect

    params = set(inspect.signature(resolve_fields).parameters)
    assert params == {"content", "filename", "recipients"}
# end def


def test_the_geometry_engine_is_gone_entirely():
    # Not merely unrouted. It was demonstrably reachable by handing its own
    # output back in as explicit fields, which made refusing "coordinates"
    # cosmetic.
    import turbosign_mcp.placement as p

    for name in ("build_coordinate_fields", "page_geometry", "Y_ORIGIN"):
        assert not hasattr(p, name), f"{name} still exists"
    # end for
# end def


# -- refusals --------------------------------------------------------------


def test_a_document_with_no_anchors_is_refused(plain_pdf, two_recipients):
    with pytest.raises(TurboSignError) as exc:
        resolve_fields(plain_pdf, "a.pdf", two_recipients)
    # end with
    assert "no signature anchors" in exc.value.message
    # The refusal has to teach, or the caller just tries again the same way.
    assert "{Signature1}" in exc.value.hint
# end def


def test_the_refusal_points_at_the_signature_block_it_found(two_recipients):
    # The most useful case: the author DID leave somewhere to sign, and just
    # needs to be told to put the anchor there.
    pdf = make_pdf("PARTY A\n   Signature: ______________________")
    with pytest.raises(TurboSignError) as exc:
        resolve_fields(pdf, "a.pdf", two_recipients)
    # end with
    assert "does have a signature block" in exc.value.hint
    assert "Put the anchors there" in exc.value.hint
# end def


def test_a_recipient_with_no_anchor_is_refused(two_recipients):
    # Half-anchored is the dangerous shape: it would send, and the omitted
    # party would get an agreement with nowhere to sign.
    pdf = make_pdf("Only one block here: {Signature1} {Date1}")
    with pytest.raises(TurboSignError) as exc:
        resolve_fields(pdf, "a.pdf", two_recipients)
    # end with
    assert "ann@example.com" in exc.value.message
# end def


def test_an_anchor_for_a_recipient_who_was_not_listed_is_refused(anchored_pdf):
    one = [{"name": "Bob", "email": "bob@example.com", "signingOrder": 1}]
    with pytest.raises(TurboSignError, match="only 1 recipient"):
        resolve_fields(anchored_pdf, "a.pdf", one)
    # end with
# end def


def test_a_non_pdf_is_refused(anchored_pdf, two_recipients):
    with pytest.raises(TurboSignError, match="only be read from a PDF"):
        resolve_fields(anchored_pdf, "contract.docx", two_recipients)
    # end with
# end def


def test_an_unreadable_file_is_reported_as_such(two_recipients):
    with pytest.raises(TurboSignError, match="could not be read as a PDF"):
        resolve_fields(b"not a pdf at all", "a.pdf", two_recipients)
    # end with
# end def


# -- the guidance the refusal hands back -----------------------------------


def test_the_guidance_covers_every_rule_that_was_got_wrong_in_practice():
    # Each of these corresponds to a way a real signature landed wrong.
    assert "ABOVE THE LINE" in ANCHOR_GUIDANCE
    assert "INVISIBLE" in ANCHOR_GUIDANCE
    assert "background colour" in ANCHOR_GUIDANCE
    assert "SIGNATURE LEFT, DATE RIGHT" in ANCHOR_GUIDANCE
    assert "POSITION IN YOUR RECIPIENTS LIST" in ANCHOR_GUIDANCE
# end def


def test_the_guidance_says_anchors_go_in_the_source_document():
    # Anchors must be real extractable text, so a finished PDF cannot gain
    # them. Advice that ignores this sends the reader in circles.
    assert "SOURCE document" in ANCHOR_GUIDANCE
# end def


def test_the_guidance_shows_a_worked_example():
    assert "{Signature1}" in ANCHOR_GUIDANCE
    assert "{Date1}" in ANCHOR_GUIDANCE
    assert "____" in ANCHOR_GUIDANCE
# end def


# -- detecting a document that has its own signature block ----------------


def test_printed_signature_lines_are_detected():
    pdf = make_pdf("PARTY A\n   Signature: ______________________\n   Date: ____")
    hints = find_signature_hints(pdf)
    assert hints
    assert any("signature" in h.lower() for h in hints)
# end def


def test_a_long_underscore_run_counts_as_a_signature_line():
    assert find_signature_hints(make_pdf("X ____________________ Y"))
# end def


def test_ordinary_prose_is_not_flagged():
    pdf = make_pdf("Effective Date: 1 August 2026\nThis agreement is binding.")
    assert find_signature_hints(pdf) == []
# end def


def test_hint_detection_survives_an_unreadable_file():
    assert find_signature_hints(b"not a pdf") == []
# end def


# -- anchor field construction --------------------------------------------


def test_build_anchor_fields_marks_every_field_required(two_recipients):
    fields = build_anchor_fields(["{Signature1}", "{Signature2}"], two_recipients)
    assert all(f["required"] for f in fields)
# end def


def test_anchor_replacement_is_case_insensitive_at_the_api(two_recipients):
    fields = build_anchor_fields(["{signature1}"], two_recipients)
    assert fields[0]["template"]["caseSensitive"] is False
# end def
