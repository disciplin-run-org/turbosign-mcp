"""The MCP surface, exercised through an in-memory client.

Unit tests prove the pieces work; these prove the server actually presents
them. The most important case is the fresh machine: an uncredentialled box
must still start and still list every tool, or the agent cannot discover the
onboarding tools it needs to fix that.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from fastmcp import Client

from turbosign_mcp.server import mcp

BASE = "https://api.turbodocx.test"

EXPECTED_TOOLS = {
    "turbosign_setup",
    "turbosign_configure",
    "turbosign_whoami",
    "turbosign_send",
    "turbosign_review",
    "turbosign_status",
    "turbosign_download",
    "turbosign_void",
    "turbosign_resend",
    "turbosign_audit_trail",
    "get_instructions",
    "refresh_tools",
}


async def _call(name: str, args: dict):
    """Call one tool through the in-memory transport and return its payload."""
    async with Client(mcp) as client:
        result = await client.call_tool(name, args)
    # end with
    if result.structured_content and "result" in result.structured_content:
        return result.structured_content["result"]
    # end if
    return result.structured_content or result.content[0].text
# end def


# -- registration ----------------------------------------------------------


async def test_every_tool_is_registered():
    async with Client(mcp) as client:
        names = {tool.name for tool in await client.list_tools()}
    # end with
    assert EXPECTED_TOOLS <= names, f"missing: {EXPECTED_TOOLS - names}"
# end def


async def test_every_tool_has_a_description():
    # The docstring is what the model reads to decide whether to call it.
    async with Client(mcp) as client:
        for tool in await client.list_tools():
            assert tool.description, f"{tool.name} has no description"
        # end for
    # end with
# end def


async def test_refresh_tools_does_not_expose_ctx_as_an_argument():
    # If the ctx parameter is not annotated `ctx: Context`, FastMCP treats it
    # as a caller argument and every invocation fails. This catches that.
    async with Client(mcp) as client:
        tool = next(t for t in await client.list_tools() if t.name == "refresh_tools")
    # end with
    assert "ctx" not in (tool.inputSchema.get("properties") or {})
# end def


async def test_the_schema_offers_no_way_to_place_a_field():
    # Anchors in the document are the only mechanism. A placement mode or a
    # fields array in the schema is an invitation to compute a position, which
    # is what put signatures in the wrong place roughly ten times.
    async with Client(mcp) as client:
        tool = next(t for t in await client.list_tools() if t.name == "turbosign_send")
    # end with
    properties = set(tool.inputSchema.get("properties", {}))
    for gone in ("placement", "fields", "anchor"):
        assert gone not in properties, f"{gone} is back in the tool schema"
    # end for
# end def


async def test_the_sender_is_required_by_the_schema_itself():
    # Stronger than validating it in the body: a required argument shows up in
    # the tool schema the model reads, so the call is unlikely to be made
    # wrong in the first place.
    async with Client(mcp) as client:
        tools = {t.name: t for t in await client.list_tools()}
    # end with
    for name in ("turbosign_send", "turbosign_review"):
        required = set(tools[name].inputSchema.get("required", []))
        assert {"sender_email", "sender_name"} <= required, (
            f"{name} does not require the sender"
        )
        assert {"file_path", "recipients"} <= required
    # end for
# end def


async def test_get_instructions_returns_the_workflow():
    text = await _call("get_instructions", {})
    assert "turbosign_review" in text
    assert "turbosign_setup" in text
# end def


async def test_instructions_carry_the_three_step_test_protocol():
    # Every consumer of this server inherits these instructions, so the
    # no-sandbox warning and the ladder have to live here rather than in a
    # README only Jesper reads.
    text = await _call("get_instructions", {})
    assert "NO TEST SANDBOX" in text
    for rung in ("turbosign_whoami(verify=True)", "turbosign_review", "YOUR OWN address"):
        assert rung in text, f"test ladder is missing {rung}"
    # end for
# end def


async def test_instructions_warn_about_the_ambiguous_default_date_format():
    # A US-format date on a cross-border contract is a real-world misread
    # waiting to happen, and the fix is a console setting this server cannot
    # reach — so the agent has to know to ask the human for it.
    text = await _call("get_instructions", {})
    assert "DATES" in text
    assert "08/01/2026" in text
    assert "account settings" in text
    assert "not retroactive" in text
# end def


async def test_the_recipient_example_in_the_instructions_actually_parses():
    """The instructions' own worked example must survive the parser.

    This is the drift-catcher. When the chain rules landed, SERVER_INSTRUCTIONS
    still advertised "Bob Smith <bob@example.com>, ann@example.com" — an
    example the new parser refuses, in the text every consumer inherits. A
    Hermes agent followed it and hit the wall. Tying the example to the code
    means the next such change breaks a test instead of a user.
    """
    from turbosign_mcp.recipients import parse_recipients

    example = "Bob Smith <bob@example.com>, Ann Jones <ann@example.com>"
    text = await _call("get_instructions", {})
    assert example in text, "the documented example changed without this test"
    parsed = parse_recipients(example)
    assert [r["email"] for r in parsed] == ["bob@example.com", "ann@example.com"]
# end def


async def test_instructions_do_not_promise_a_geometry_fallback():
    # The fallback was removed. Instructions promising it send the agent
    # looking for a mode that no longer exists.
    text = await _call("get_instructions", {})
    assert "foot of the last page" not in text
    assert "any other PDF still works" not in text
    assert "no placement argument, no" in text
    assert "no fallback to look for" in text
# end def


async def test_instructions_teach_the_anchor_layout():
    # The layout IS the product knowledge here — an agent that anchors a
    # document wrongly produces a plausible-looking agreement signed in the
    # wrong place. Served from placement.ANCHOR_GUIDANCE so the instructions
    # and the refusal message cannot disagree.
    from turbosign_mcp.placement import ANCHOR_GUIDANCE

    text = await _call("get_instructions", {})
    assert ANCHOR_GUIDANCE in text, "the anchor guidance is not being served"
    assert "__ANCHOR_GUIDANCE__" not in text, "the placeholder was never filled"
# end def


async def test_instructions_state_every_chain_rule():
    # All four are refusals an agent will hit. Two of them — the allowlist and
    # the per-send sender — it cannot discover from the tool schema alone.
    text = await _call("get_instructions", {})
    for rule in (
        "NAMES ARE EXPLICIT",
        "THE SENDER IS PER-SEND",
        "TURBOSIGN_ALLOWED_SIGNERS",
        "THE DOCUMENT DECLARES THE CHAIN",
    ):
        assert rule in text, f"instructions do not mention {rule}"
    # end for
# end def


async def test_instructions_cover_a_document_with_printed_signature_lines():
    # The case Hermes reported: a PDF with a visible signature block but no
    # anchor tokens. It is now refused, so the agent needs to know to check
    # before calling, and that the fix is in the source document.
    text = await _call("get_instructions", {})
    assert "BEFORE CALLING review OR send" in text
    assert "signature block" in text
    assert "fix the SOURCE document" in text
# end def


async def test_instructions_tell_hosts_to_gate_send_but_not_review():
    text = await _call("get_instructions", {})
    assert "human approval" in text
    assert "Leave turbosign_review ungated" in text
# end def


async def test_the_send_tool_warns_on_its_own_description():
    # A model may read the tool schema without ever seeing the server
    # instructions, so the irreversibility warning has to be on the tool too.
    async with Client(mcp) as client:
        tool = next(t for t in await client.list_tools() if t.name == "turbosign_send")
    # end with
    assert "NO SANDBOX" in tool.description
    assert "cannot be recalled" in tool.description
# end def


# -- the fresh-machine state ----------------------------------------------


async def test_an_unconfigured_machine_still_lists_every_tool(isolated_home):
    async with Client(mcp) as client:
        names = {tool.name for tool in await client.list_tools()}
    # end with
    assert EXPECTED_TOOLS <= names
# end def


async def test_setup_names_what_is_missing_and_where_to_get_it(isolated_home):
    text = await _call("turbosign_setup", {})
    assert "not ready to send" in text
    assert "MISSING" in text
    assert "Settings -> API Keys" in text
    assert "turbosign_configure" in text
# end def


async def test_sending_without_credentials_points_at_setup(isolated_home, tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    result = await _call(
        "turbosign_send",
        {
            "file_path": str(pdf),
            "recipients": "Bob Smith <bob@example.com>",
            "sender_email": "sender@example.com",
            "sender_name": "Test Sender",
        },
    )
    assert result["ok"] is False
    assert "turbosign_setup" in result["hint"]
# end def


async def test_whoami_on_a_fresh_machine_reports_unconfigured(isolated_home):
    result = await _call("turbosign_whoami", {"verify": False})
    assert result["configured"] is False
    assert "TURBODOCX_API_KEY" in result["missing"]
# end def


# -- onboarding ------------------------------------------------------------


@respx.mock
async def test_configure_verifies_before_it_saves(isolated_home):
    from turbosign_mcp import credentials

    respx.get(url__regex=r".*/turbosign/documents/.*/status").mock(
        return_value=httpx.Response(401, json={"message": "Unauthorized"})
    )
    result = await _call(
        "turbosign_configure",
        {
            "api_key": "wrong",
            "org_id": "o",
            "sender_email": "s@example.com",
            "base_url": BASE,
        },
    )
    assert result["ok"] is False
    # The point of the tool: a key that does not work is never written.
    assert credentials.load_store() == {}
# end def


@respx.mock
async def test_configure_saves_a_working_key_and_masks_it(isolated_home):
    from turbosign_mcp import credentials

    respx.get(url__regex=r".*/turbosign/documents/.*/status").mock(
        return_value=httpx.Response(404, json={"message": "Not found"})
    )
    result = await _call(
        "turbosign_configure",
        {
            "api_key": "sk-live-abcdefghijkl",
            "org_id": "org-1",
            "sender_email": "s@example.com",
            "base_url": BASE,
        },
    )
    assert result["ok"] is True
    assert credentials.load_store()["api_key"] == "sk-live-abcdefghijkl"
    # The key itself must never come back out of a tool.
    assert "sk-live-abcdefghijkl" not in json.dumps(result)
    assert result["api_key"].endswith("ijkl")
# end def


async def test_configure_refuses_a_blank_required_field(isolated_home):
    result = await _call(
        "turbosign_configure",
        {"api_key": "k", "org_id": "", "sender_email": "s@example.com"},
    )
    assert result["ok"] is False
    assert "org_id is required" in result["error"]
# end def


# -- signing, end to end over the transport --------------------------------


@pytest.fixture
def configured(isolated_home, monkeypatch, tmp_path):
    """A machine with working credentials and a sandbox to send from."""
    monkeypatch.setenv("TURBODOCX_API_KEY", "k")
    monkeypatch.setenv("TURBODOCX_ORG_ID", "o")
    monkeypatch.setenv("TURBODOCX_SENDER_EMAIL", "sender@example.com")
    monkeypatch.setenv("TURBODOCX_BASE_URL", BASE)
    monkeypatch.setenv("TURBOSIGN_ALLOWED_DIRS", str(tmp_path))
    # No allowlist means no send: an unconfigured allowlist refuses everything
    # rather than allowing everything. See chain.require_allowed_signers.
    monkeypatch.setenv("TURBOSIGN_ALLOWED_SIGNERS", "@example.com")
    return tmp_path
# end def


@respx.mock
async def test_send_reports_the_document_id_and_the_strategy_used(configured):
    from .conftest import make_pdf

    pdf = configured / "nda.pdf"
    pdf.write_bytes(make_pdf("Agreement. Sign here: {Signature1}"))

    respx.post(f"{BASE}/turbosign/single/prepare-for-signing").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "documentId": "doc-9",
                "status": "UNDER_REVIEW",
                "recipients": [
                    {"id": "r1", "name": "Bob", "email": "bob@example.com",
                     "signingOrder": 1}
                ],
            },
        )
    )

    result = await _call(
        "turbosign_send",
        {
            "file_path": str(pdf),
            "recipients": "Bob Smith <bob@example.com>",
            "sender_email": "sender@example.com",
            "sender_name": "Test Sender",
        },
    )
    assert result["ok"] is True
    assert result["document_id"] == "doc-9"
    assert result["placement"] == "anchor"
    assert result["emails_sent"] is True
    assert result["recipients"][0]["id"] == "r1"
# end def


@respx.mock
async def test_send_uses_anchors_when_the_pdf_has_them(configured):
    from .conftest import make_pdf

    pdf = configured / "anchored.pdf"
    pdf.write_bytes(make_pdf("Sign here: {Signature1}"))

    route = respx.post(f"{BASE}/turbosign/single/prepare-for-signing").mock(
        return_value=httpx.Response(200, json={"documentId": "doc-1"})
    )
    result = await _call(
        "turbosign_send",
        {
            "file_path": str(pdf),
            "recipients": "Bob Smith <bob@example.com>",
            "sender_email": "sender@example.com",
            "sender_name": "Test Sender",
        },
    )
    assert result["placement"] == "anchor"
    assert route.called
# end def


@respx.mock
async def test_review_sends_no_emails_and_returns_a_preview(configured):
    from .conftest import make_pdf

    pdf = configured / "nda.pdf"
    pdf.write_bytes(make_pdf("Sign here: {Signature1}"))

    respx.post(f"{BASE}/turbosign/single/prepare-for-review").mock(
        return_value=httpx.Response(
            200,
            json={"documentId": "d1", "status": "REVIEW_READY",
                  "previewUrl": "https://preview.test/d1"},
        )
    )
    result = await _call(
        "turbosign_review",
        {
            "file_path": str(pdf),
            "recipients": "Bob Smith <bob@example.com>",
            "sender_email": "sender@example.com",
            "sender_name": "Test Sender",
        },
    )
    assert result["emails_sent"] is False
    assert result["preview_url"] == "https://preview.test/d1"
# end def


@respx.mock
async def test_download_writes_the_signed_pdf(configured):
    respx.get(f"{BASE}/turbosign/documents/d1/download").mock(
        return_value=httpx.Response(200, json={"downloadUrl": "https://s3.test/s.pdf"})
    )
    respx.get("https://s3.test/s.pdf").mock(
        return_value=httpx.Response(200, content=b"%PDF-signed-bytes")
    )
    target = configured / "signed.pdf"
    result = await _call(
        "turbosign_download", {"document_id": "d1", "output_path": str(target)}
    )
    assert result["ok"] is True
    assert target.read_bytes() == b"%PDF-signed-bytes"
# end def


async def test_void_requires_a_reason(configured):
    result = await _call("turbosign_void", {"document_id": "d1", "reason": "  "})
    assert result["ok"] is False
    assert "reason is required" in result["error"]
# end def


@respx.mock
async def test_resend_splits_a_comma_separated_id_list(configured):
    route = respx.post(f"{BASE}/turbosign/documents/d1/resend-email").mock(
        return_value=httpx.Response(200, json={"data": {"recipientCount": 2}})
    )
    await _call("turbosign_resend", {"document_id": "d1", "recipient_ids": "r1, r2"})
    assert json.loads(route.calls[0].request.content) == {"recipientIds": ["r1", "r2"]}
# end def


async def test_resend_without_ids_says_where_to_get_them(configured):
    result = await _call("turbosign_resend", {"document_id": "d1", "recipient_ids": ""})
    assert result["ok"] is False
    assert "turbosign_status" in result["hint"]
# end def


@respx.mock
async def test_audit_trail_names_the_recipient_an_action_concerns(configured):
    # Shape copied from a real api.turbodocx.com response. The top-level
    # `recipient` is null on every entry the API returns; the recipient lives
    # in details.recipientInfo. Reading only the top level made this tool
    # answer "who was emailed?" with null.
    respx.get(f"{BASE}/turbosign/documents/d1/audit-trail").mock(
        return_value=httpx.Response(200, json={"data": {
            "document": {"id": "d1"},
            "auditTrail": [{
                "actionType": "email_notification_sent",
                "timestamp": "2026-08-02T00:08:11.000Z",
                "recipient": None,
                "details": {
                    "message": "Signature request notification email sent to "
                               "Jesper Test (test@jurcenoks.com)",
                    "recipientInfo": {"id": "r1", "name": "Jesper Test",
                                      "email": "test@jurcenoks.com"},
                },
            }],
        }})
    )
    result = await _call("turbosign_audit_trail", {"document_id": "d1"})
    entry = result["entries"][0]
    assert entry["recipient"] == "test@jurcenoks.com"
    assert entry["recipient_name"] == "Jesper Test"
    assert "email sent to" in entry["message"]
# end def


@respx.mock
async def test_audit_trail_truncates_a_long_detail_message(configured):
    # The pdf-updated entry's message runs to several hundred characters of
    # file ids; unbounded, it would bloat the agent's context.
    respx.get(f"{BASE}/turbosign/documents/d1/audit-trail").mock(
        return_value=httpx.Response(200, json={"data": {"auditTrail": [{
            "actionType": "document_pdf_updated",
            "details": {"message": "x" * 900},
        }]}})
    )
    result = await _call("turbosign_audit_trail", {"document_id": "d1"})
    assert len(result["entries"][0]["message"]) < 300
    assert result["entries"][0]["message"].endswith("...")
# end def


@respx.mock
async def test_audit_trail_is_trimmed_to_the_limit(configured):
    entries = [
        {"actionType": f"a{i}", "timestamp": f"t{i}"} for i in range(10)
    ]
    respx.get(f"{BASE}/turbosign/documents/d1/audit-trail").mock(
        return_value=httpx.Response(
            200, json={"data": {"document": {"id": "d1"}, "auditTrail": entries}}
        )
    )
    result = await _call(
        "turbosign_audit_trail", {"document_id": "d1", "limit": 3}
    )
    assert len(result["entries"]) == 3
    assert result["total_entries"] == 10
    assert result["truncated"] is True
# end def


@respx.mock
async def test_an_api_error_comes_back_as_guidance_not_a_traceback(configured):
    respx.get(f"{BASE}/turbosign/documents/d1/status").mock(
        return_value=httpx.Response(401, json={"message": "Unauthorized"})
    )
    result = await _call("turbosign_status", {"document_id": "d1"})
    assert result["ok"] is False
    assert result["hint"]
# end def


# ── the chain rules, exercised through the tool surface ──────────────────────
#
# tests/test_chain_integrity.py proves each rule in isolation. These prove they
# are actually WIRED — a rule that is never called is the same as no rule, and
# that failure mode looks identical to a passing unit test.
#
# Every one of these asserts the request was refused BEFORE any HTTP call. No
# respx route is registered, so if a request escaped, it would error on the
# unmocked call rather than pass quietly.


@respx.mock
async def test_send_refuses_an_unnamed_recipient(configured):
    from .conftest import make_pdf

    pdf = configured / "nda.pdf"
    pdf.write_bytes(make_pdf("Sign here: {Signature1}"))
    result = await _call(
        "turbosign_send",
        {
            "file_path": str(pdf),
            "recipients": "bob@example.com",          # no name
            "sender_email": "sender@example.com",
            "sender_name": "Test Sender",
        },
    )
    assert result["ok"] is False
    assert "name" in str(result).lower()
# end def


@respx.mock
async def test_send_refuses_a_signer_off_the_allowlist(configured):
    """A fully named stranger at a lookalike domain — what naming cannot see."""
    from .conftest import make_pdf

    pdf = configured / "nda.pdf"
    pdf.write_bytes(make_pdf("Sign here: {Signature1}"))
    result = await _call(
        "turbosign_send",
        {
            "file_path": str(pdf),
            "recipients": "Bob Smith <bob@example-invoices.com>",
            "sender_email": "sender@example.com",
            "sender_name": "Test Sender",
        },
    )
    assert result["ok"] is False
    assert "allowlist" in str(result).lower()
# end def


@respx.mock
async def test_send_refuses_a_recipient_the_document_does_not_name(configured):
    """Two signature blocks, three people. The third would have nothing to sign."""
    from .conftest import make_pdf

    pdf = configured / "nda.pdf"
    pdf.write_bytes(make_pdf("A: {Signature1}  B: {Signature2}"))
    result = await _call(
        "turbosign_send",
        {
            "file_path": str(pdf),
            "recipients": ("A One <a@example.com>, B Two <b@example.com>, "
                           "C Three <c@example.com>"),
            "sender_email": "sender@example.com",
            "sender_name": "Test Sender",
        },
    )
    assert result["ok"] is False
    assert "anchor" in str(result).lower()
# end def


@respx.mock
async def test_send_refuses_a_blank_sender(configured):
    # Omitting the argument entirely is now caught by the schema (see
    # test_the_sender_is_required_by_the_schema_itself). Passing it EMPTY is
    # the case that still reaches our code, and it has to explain itself
    # rather than quietly sending as nobody.
    from .conftest import make_pdf

    pdf = configured / "nda.pdf"
    pdf.write_bytes(make_pdf("Sign here: {Signature1}"))
    result = await _call(
        "turbosign_send",
        {
            "file_path": str(pdf),
            "recipients": "Bob Smith <bob@example.com>",
            "sender_email": "",
            "sender_name": "",
        },
    )
    assert result["ok"] is False
    assert "sender" in str(result).lower()
    assert "per-send decision" in result["hint"]
# end def


@respx.mock
async def test_review_is_held_to_the_same_rules(configured):
    """The rehearsal must exercise every check the send does.

    A review that skipped validation would return a clean preview for a request
    that could never be sent — which is worse than no rehearsal, because it
    reads as approval.
    """
    from .conftest import make_pdf

    pdf = configured / "nda.pdf"
    pdf.write_bytes(make_pdf("Sign here: {Signature1}"))
    result = await _call(
        "turbosign_review",
        {
            "file_path": str(pdf),
            "recipients": "bob@example.com",          # no name
            "sender_email": "sender@example.com",
            "sender_name": "Test Sender",
        },
    )
    assert result["ok"] is False
# end def
