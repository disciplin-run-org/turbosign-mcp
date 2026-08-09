"""The wire contract, asserted against a mocked transport.

These are the tests that pin the things easiest to get quietly wrong: that
``recipients`` and ``fields`` go up as *stringified* JSON even inside a
multipart body, that ``senderEmail`` is always present, and that the two
required auth headers are on every request.

Contract source: the published API reference plus TurboDocx/SDK's
``packages/py-sdk/src/turbodocx_sdk/modules/sign.py``.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from turbosign_mcp.api import TurboSignClient
from turbosign_mcp.errors import TurboSignError

BASE = "https://api.turbodocx.test"

RECIPIENTS = [{"name": "Bob", "email": "bob@example.com", "signingOrder": 1}]
FIELDS = [{"type": "signature", "recipientEmail": "bob@example.com", "page": 1}]


def _multipart_fields(request: httpx.Request) -> dict[str, str]:
    """Pull the non-file form fields out of a multipart body."""
    body = request.content.decode("utf-8", errors="replace")
    out: dict[str, str] = {}
    for part in body.split("--" + request.headers["content-type"].split("boundary=")[1]):
        if 'name="' not in part:
            continue
        # end if
        name = part.split('name="', 1)[1].split('"', 1)[0]
        if "filename=" in part:
            continue
        # end if
        value = part.split("\r\n\r\n", 1)[-1].rsplit("\r\n", 1)[0]
        out[name] = value
    # end for
    return out
# end def


# -- headers ---------------------------------------------------------------


@respx.mock
def test_every_request_carries_both_auth_headers(settings):
    route = respx.get(f"{BASE}/turbosign/documents/doc-1/status").mock(
        return_value=httpx.Response(200, json={"status": "pending"})
    )
    TurboSignClient(settings).get_status("doc-1")

    headers = route.calls[0].request.headers
    assert headers["authorization"] == "Bearer test-key"
    assert headers["x-rapiddocx-org-id"] == "test-org"
    assert "TurboDocx API Client" in headers["user-agent"]
# end def


# -- prepare-for-signing ---------------------------------------------------


@respx.mock
def test_send_posts_multipart_with_stringified_json(settings):
    route = respx.post(f"{BASE}/turbosign/single/prepare-for-signing").mock(
        return_value=httpx.Response(200, json={"success": True, "documentId": "d1"})
    )

    TurboSignClient(settings).prepare_for_signing(
        recipients=RECIPIENTS,
        fields=FIELDS,
        content=b"%PDF-1.4 fake",
        filename="nda.pdf",
        document_name="NDA",
        # Stated explicitly: the client stopped inheriting the sender from
        # settings, so that a months-old config value cannot end up as the
        # reply-to on a contract. See src/turbosign_mcp/chain.py.
        sender_email="sender@example.com",
    )

    request = route.calls[0].request
    assert request.headers["content-type"].startswith("multipart/form-data")
    form = _multipart_fields(request)

    # The critical bit: these are JSON *strings*, not nested form structures.
    assert json.loads(form["recipients"]) == RECIPIENTS
    assert json.loads(form["fields"]) == FIELDS
    assert form["senderEmail"] == "sender@example.com"
    assert form["documentName"] == "NDA"
    assert b"nda.pdf" in request.content
# end def


@respx.mock
def test_send_by_file_link_posts_json_with_stringified_json(settings):
    route = respx.post(f"{BASE}/turbosign/single/prepare-for-signing").mock(
        return_value=httpx.Response(200, json={"documentId": "d1"})
    )

    TurboSignClient(settings).prepare_for_signing(
        recipients=RECIPIENTS,
        fields=FIELDS,
        file_link="https://example.com/nda.pdf",
    )

    body = json.loads(route.calls[0].request.content)
    # Same stringification rule applies to the JSON body — this is the part
    # that surprises people.
    assert json.loads(body["recipients"]) == RECIPIENTS
    assert json.loads(body["fields"]) == FIELDS
    assert body["fileLink"] == "https://example.com/nda.pdf"
# end def


@respx.mock
def test_sender_name_and_cc_are_included_when_set(settings):
    route = respx.post(f"{BASE}/turbosign/single/prepare-for-signing").mock(
        return_value=httpx.Response(200, json={"documentId": "d1"})
    )
    TurboSignClient(settings).prepare_for_signing(
        recipients=RECIPIENTS,
        fields=FIELDS,
        content=b"%PDF",
        filename="a.pdf",
        cc_emails=["watch@example.com"],
        sender_name="Test Sender",
    )
    form = _multipart_fields(route.calls[0].request)
    assert form["senderName"] == "Test Sender"
    assert json.loads(form["ccEmails"]) == ["watch@example.com"]
# end def


@respx.mock
def test_document_name_is_truncated_to_the_api_limit(settings):
    route = respx.post(f"{BASE}/turbosign/single/prepare-for-signing").mock(
        return_value=httpx.Response(200, json={"documentId": "d1"})
    )
    TurboSignClient(settings).prepare_for_signing(
        recipients=RECIPIENTS, fields=FIELDS, content=b"%PDF",
        filename="a.pdf", document_name="x" * 400,
    )
    assert len(_multipart_fields(route.calls[0].request)["documentName"]) == 255
# end def


# -- the other endpoints ---------------------------------------------------


@respx.mock
def test_review_hits_the_review_endpoint(settings):
    route = respx.post(f"{BASE}/turbosign/single/prepare-for-review").mock(
        return_value=httpx.Response(200, json={"previewUrl": "https://p/1"})
    )
    body = TurboSignClient(settings).prepare_for_review(
        recipients=RECIPIENTS, fields=FIELDS, content=b"%PDF", filename="a.pdf"
    )
    assert route.called
    assert body["previewUrl"] == "https://p/1"
# end def


@respx.mock
def test_void_posts_the_reason(settings):
    route = respx.post(f"{BASE}/turbosign/documents/d1/void").mock(
        return_value=httpx.Response(200, json={"status": "voided"})
    )
    TurboSignClient(settings).void("d1", "superseded")
    assert json.loads(route.calls[0].request.content) == {"reason": "superseded"}
# end def


@respx.mock
def test_resend_posts_recipient_ids(settings):
    route = respx.post(f"{BASE}/turbosign/documents/d1/resend-email").mock(
        return_value=httpx.Response(200, json={"data": {"recipientCount": 2}})
    )
    TurboSignClient(settings).resend("d1", ["r1", "r2"])
    assert json.loads(route.calls[0].request.content) == {"recipientIds": ["r1", "r2"]}
# end def


@respx.mock
def test_audit_trail_is_a_get(settings):
    respx.get(f"{BASE}/turbosign/documents/d1/audit-trail").mock(
        return_value=httpx.Response(200, json={"data": {"auditTrail": []}})
    )
    assert TurboSignClient(settings).audit_trail("d1")["data"]["auditTrail"] == []
# end def


@respx.mock
def test_download_follows_the_presigned_url(settings):
    respx.get(f"{BASE}/turbosign/documents/d1/download").mock(
        return_value=httpx.Response(200, json={"downloadUrl": "https://s3.test/x.pdf"})
    )
    respx.get("https://s3.test/x.pdf").mock(
        return_value=httpx.Response(200, content=b"%PDF-signed")
    )
    client = TurboSignClient(settings)
    assert client.fetch_signed(client.get_download_url("d1")) == b"%PDF-signed"
# end def


@respx.mock
def test_a_missing_download_url_is_explained(settings):
    respx.get(f"{BASE}/turbosign/documents/d1/download").mock(
        return_value=httpx.Response(200, json={})
    )
    with pytest.raises(TurboSignError, match="did not return a download URL"):
        TurboSignClient(settings).get_download_url("d1")
    # end with
# end def


@respx.mock
def test_an_expired_presigned_link_says_so(settings):
    respx.get("https://s3.test/x.pdf").mock(return_value=httpx.Response(403))
    with pytest.raises(TurboSignError) as excinfo:
        TurboSignClient(settings).fetch_signed("https://s3.test/x.pdf")
    # end with
    assert "expire" in excinfo.value.hint
# end def


# -- error mapping ---------------------------------------------------------


@respx.mock
@pytest.mark.parametrize(
    "status,body,expect_in_hint",
    [
        (401, {"message": "Unauthorized"}, "turbosign_whoami"),
        (403, {"message": "Forbidden"}, "console"),
        (404, {"message": "Not found"}, "document_id"),
        (400, {"message": "SenderEmailRequired"}, "sender_email"),
        (422, {"message": "bad field"}, "turbosign_review"),
        (500, {"message": "boom"}, "retry"),
    ],
)
def test_http_errors_become_actionable_sentences(settings, status, body, expect_in_hint):
    respx.get(f"{BASE}/turbosign/documents/d1/status").mock(
        return_value=httpx.Response(status, json=body)
    )
    with pytest.raises(TurboSignError) as excinfo:
        TurboSignClient(settings).get_status("d1")
    # end with
    error = excinfo.value
    assert expect_in_hint in error.hint
    # An agent should never receive a bare status code with no guidance.
    assert error.hint
    assert error.as_result()["ok"] is False
# end def


@respx.mock
def test_rate_limiting_passes_on_retry_after(settings):
    respx.get(f"{BASE}/turbosign/documents/d1/status").mock(
        return_value=httpx.Response(429, headers={"retry-after": "30"}, json={})
    )
    with pytest.raises(TurboSignError) as excinfo:
        TurboSignClient(settings).get_status("d1")
    # end with
    assert "30" in excinfo.value.hint
# end def


@respx.mock
def test_a_timeout_suggests_the_knob_that_fixes_it(settings):
    respx.get(f"{BASE}/turbosign/documents/d1/status").mock(
        side_effect=httpx.ReadTimeout("too slow")
    )
    with pytest.raises(TurboSignError) as excinfo:
        TurboSignClient(settings).get_status("d1")
    # end with
    assert "TURBOSIGN_TIMEOUT" in excinfo.value.hint
# end def


@respx.mock
def test_an_unreachable_host_names_the_url(settings):
    respx.get(f"{BASE}/turbosign/documents/d1/status").mock(
        side_effect=httpx.ConnectError("no route")
    )
    with pytest.raises(TurboSignError, match="Could not reach TurboSign"):
        TurboSignClient(settings).get_status("d1")
    # end with
# end def


# -- the credential probe --------------------------------------------------


@respx.mock
def test_a_working_key_probes_clean(settings):
    # A valid key looking up a nonexistent document gets 404.
    respx.get(url__regex=rf"{BASE}/turbosign/documents/.*/status").mock(
        return_value=httpx.Response(404, json={"message": "Not found"})
    )
    ok, detail = TurboSignClient(settings).probe()
    assert ok is True
    assert "accepted" in detail
# end def


@respx.mock
def test_a_bad_key_fails_the_probe(settings):
    respx.get(url__regex=rf"{BASE}/turbosign/documents/.*/status").mock(
        return_value=httpx.Response(401, json={"message": "Unauthorized"})
    )
    ok, detail = TurboSignClient(settings).probe()
    assert ok is False
    assert "401" in detail
# end def


@respx.mock
def test_an_unexpected_probe_result_is_reported_not_guessed(settings):
    # If the 401-vs-404 assumption ever stops holding, this must surface as a
    # clear failure rather than a silent pass. See docs/VERIFICATION.md.
    respx.get(url__regex=rf"{BASE}/turbosign/documents/.*/status").mock(
        return_value=httpx.Response(500, json={"message": "boom"})
    )
    ok, detail = TurboSignClient(settings).probe()
    assert ok is False
    assert "Could not verify" in detail
# end def


def test_an_unconfigured_client_refuses_to_be_built():
    from dataclasses import replace

    from turbosign_mcp.errors import NotConfiguredError

    blank = replace(
        __import__("turbosign_mcp.config", fromlist=["Settings"]).Settings(
            api_key=None, org_id=None, sender_email=None, sender_name=None,
            base_url=BASE,
        )
    )
    with pytest.raises(NotConfiguredError):
        TurboSignClient(blank)
    # end with
# end def
