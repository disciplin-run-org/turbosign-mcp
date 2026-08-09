"""Field placement — anchors when they exist, geometry when they do not."""

from __future__ import annotations

import pytest

from turbosign_mcp import placement
from turbosign_mcp.errors import TurboSignError
from turbosign_mcp.placement import (
    build_coordinate_fields,
    find_anchors,
    page_geometry,
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


# -- auto: anchors win when present ---------------------------------------


def test_auto_uses_anchors_when_the_document_has_them(anchored_pdf, two_recipients):
    fields, strategy = resolve_fields(
        anchored_pdf, "a.pdf", two_recipients, placement="auto"
    )
    assert strategy == "anchor"
    assert all("template" in f for f in fields)
    assert fields[0]["template"]["anchor"] == "{Signature1}"
# end def


def test_anchor_index_selects_the_recipient(anchored_pdf, two_recipients):
    fields, _ = resolve_fields(anchored_pdf, "a.pdf", two_recipients, placement="auto")
    by_anchor = {f["template"]["anchor"]: f["recipientEmail"] for f in fields}
    assert by_anchor["{Signature1}"] == "bob@example.com"
    assert by_anchor["{Signature2}"] == "ann@example.com"
# end def


def test_anchor_kind_maps_to_field_type(anchored_pdf, two_recipients):
    fields, _ = resolve_fields(anchored_pdf, "a.pdf", two_recipients, placement="auto")
    types = {f["template"]["anchor"]: f["type"] for f in fields}
    assert types["{Signature1}"] == "signature"
    assert types["{Date1}"] == "date"
# end def


def test_anchor_for_a_recipient_who_was_not_listed_is_an_error(anchored_pdf):
    one = [{"name": "Bob", "email": "bob@example.com", "signingOrder": 1}]
    with pytest.raises(TurboSignError, match="only 1 recipient"):
        resolve_fields(anchored_pdf, "a.pdf", one, placement="auto")
    # end with
# end def


# -- auto: an unanchored document is refused, not measured ----------------


def test_auto_refuses_a_document_with_no_anchors(plain_pdf, two_recipients):
    """This used to fall back to geometry and send.

    A document positioned by measurement declares nothing about who signs it,
    so the recipient list cannot be checked against anything. That is the hole
    the fallback left open, and it is why it is gone.
    """
    with pytest.raises(TurboSignError) as exc:
        resolve_fields(plain_pdf, "a.pdf", two_recipients, placement="auto")
    assert "anchor" in str(exc.value).lower()
# end def


def test_coordinates_placement_is_refused_by_name(two_recipients):
    """Rejected explicitly rather than left to fail later as "no anchors".

    An error naming the mode the caller asked for is the difference between a
    decision and a bug.
    """
    pdf = make_pdf("no anchors here", pages=3)
    with pytest.raises(TurboSignError) as exc:
        resolve_fields(pdf, "a.pdf", two_recipients, placement="coordinates")
    assert "coordinates" in str(exc.value)
# end def


def test_coordinate_fields_satisfy_the_api_validation_rule(two_recipients):
    # The API rejects anything where x+width > pageWidth or y+height > pageHeight.
    pdf = make_pdf("", pages=1)
    fields = build_coordinate_fields(pdf, two_recipients)
    for field in fields:
        assert field["x"] >= 0
        assert field["y"] >= 0
        assert field["x"] + field["width"] <= field["pageWidth"]
        assert field["y"] + field["height"] <= field["pageHeight"]
    # end for
# end def


def test_each_recipient_gets_their_own_row(two_recipients):
    fields = build_coordinate_fields(make_pdf(""), two_recipients)
    rows = {f["recipientEmail"]: f["y"] for f in fields if f["type"] == "signature"}
    assert rows["bob@example.com"] != rows["ann@example.com"]
# end def


def test_too_many_recipients_to_fit_is_refused_before_the_api_sees_it():
    many = [
        {"name": f"P{i}", "email": f"p{i}@example.com", "signingOrder": 1}
        for i in range(12)
    ]
    with pytest.raises(TurboSignError, match="do not fit"):
        build_coordinate_fields(make_pdf("", height=200), many)
    # end with
# end def


def test_page_geometry_reads_a_non_default_page_size():
    count, width, height = page_geometry(make_pdf("", pages=2, width=842, height=595))
    assert (count, round(width), round(height)) == (2, 842, 595)
# end def


# -- the coordinate-origin assumption -------------------------------------


def test_the_y_origin_matches_the_verified_live_behaviour():
    # Not a guess: verified 2026-08-01 against api.turbodocx.com, where a
    # review of an unanchored PDF put the boxes at the foot of the page.
    # If a future API change moves them, flip this constant and this test
    # together — nothing else depends on it. See docs/VERIFICATION.md.
    assert placement.Y_ORIGIN == "top"
# end def


def test_top_origin_puts_the_first_row_near_the_page_bottom(two_recipients):
    fields = build_coordinate_fields(make_pdf(""), two_recipients[:1])
    signature = next(f for f in fields if f["type"] == "signature")
    # With a top-left origin, "near the bottom" means a large y.
    assert signature["y"] > signature["pageHeight"] * 0.8
# end def


# -- explicit and forced modes --------------------------------------------


def test_explicit_fields_are_passed_through_untouched(plain_pdf, two_recipients):
    given = [{"type": "signature", "recipientEmail": "bob@example.com", "page": 1}]
    fields, strategy = resolve_fields(
        plain_pdf, "a.pdf", two_recipients, placement="auto", fields=given
    )
    assert strategy == "explicit"
    assert fields == given
# end def


def test_explicit_fields_accept_a_json_string(plain_pdf, two_recipients):
    fields, strategy = resolve_fields(
        plain_pdf,
        "a.pdf",
        two_recipients,
        fields='[{"type": "signature", "recipientEmail": "bob@example.com"}]',
    )
    assert strategy == "explicit"
    assert fields[0]["type"] == "signature"
# end def


def test_forcing_anchor_mode_without_anchors_fails_helpfully(plain_pdf, two_recipients):
    with pytest.raises(TurboSignError) as excinfo:
        resolve_fields(plain_pdf, "a.pdf", two_recipients, placement="anchor")
    # end with
    assert "{Signature1}" in excinfo.value.hint
# end def


def test_a_named_anchor_is_used_directly(anchored_pdf, two_recipients):
    fields, strategy = resolve_fields(
        anchored_pdf, "a.pdf", two_recipients, anchor="{Signature2}"
    )
    assert strategy == "anchor"
    assert fields[0]["recipientEmail"] == "ann@example.com"
# end def


def test_non_pdf_cannot_be_measured_and_says_why(plain_pdf, two_recipients):
    with pytest.raises(TurboSignError, match="only read PDFs"):
        resolve_fields(plain_pdf, "contract.docx", two_recipients, placement="auto")
    # end with
# end def


def test_an_unreadable_file_is_reported_as_such(two_recipients):
    with pytest.raises(TurboSignError, match="could not be read as a PDF"):
        resolve_fields(b"not a pdf at all", "a.pdf", two_recipients)
    # end with
# end def
