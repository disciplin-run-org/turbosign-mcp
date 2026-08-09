"""Recipient parsing — the ergonomics that make a one-line send possible."""

from __future__ import annotations

import pytest

from turbosign_mcp.errors import TurboSignError
from turbosign_mcp.recipients import parse_recipients


def test_named_address():
    assert parse_recipients("Bob Smith <bob@example.com>") == [
        {"name": "Bob Smith", "email": "bob@example.com", "signingOrder": 1}
    ]
# end def


def test_bare_address_gets_a_derived_name():
    out = parse_recipients("ann.jones@example.com")
    assert out[0]["email"] == "ann.jones@example.com"
    assert out[0]["name"] == "Ann Jones"
# end def


def test_several_recipients_split_on_commas():
    out = parse_recipients("Bob <bob@example.com>, ann@example.com")
    assert [r["email"] for r in out] == ["bob@example.com", "ann@example.com"]
# end def


def test_comma_inside_a_display_name_is_not_a_separator():
    out = parse_recipients("Smith, Bob <bob@example.com>")
    assert len(out) == 1
    assert out[0]["name"] == "Smith, Bob"
# end def


def test_parallel_signing_is_the_default():
    out = parse_recipients("a@example.com, b@example.com")
    assert [r["signingOrder"] for r in out] == [1, 1]
# end def


def test_sequential_numbers_recipients_in_order():
    out = parse_recipients("a@example.com, b@example.com", sequential=True)
    assert [r["signingOrder"] for r in out] == [1, 2]
# end def


def test_json_array_is_accepted():
    out = parse_recipients('[{"name": "Bob", "email": "bob@example.com"}]')
    assert out[0]["name"] == "Bob"
# end def


def test_explicit_signing_order_is_respected():
    out = parse_recipients(
        [
            {"name": "Bob", "email": "bob@example.com", "signingOrder": 2},
            {"name": "Ann", "email": "ann@example.com", "signingOrder": 1},
        ]
    )
    assert {r["email"]: r["signingOrder"] for r in out} == {
        "bob@example.com": 2,
        "ann@example.com": 1,
    }
# end def


def test_duplicate_address_is_refused():
    # The API requires unique recipient emails, so catch it before the call.
    with pytest.raises(TurboSignError, match="twice"):
        parse_recipients("bob@example.com, Bob <BOB@example.com>")
    # end with
# end def


def test_empty_input_is_refused():
    with pytest.raises(TurboSignError, match="No recipients"):
        parse_recipients("")
    # end with
# end def


def test_nonsense_is_refused_with_an_example():
    with pytest.raises(TurboSignError) as excinfo:
        parse_recipients("just some words")
    # end with
    assert "bob@example.com" in excinfo.value.hint
# end def


def test_malformed_json_says_so():
    with pytest.raises(TurboSignError, match="would not parse"):
        parse_recipients('[{"email": ]')
    # end with
# end def
