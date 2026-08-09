"""HTTP client for the seven TurboSign endpoints.

Deliberately plain ``httpx`` rather than the ``turbodocx-sdk`` package: this
server *is* the thin wrapper, and stacking it on a second wrapper buys endpoint
drift protection at the cost of a pre-1.0 dependency and someone else's error
messages. Seven endpoints whose contract is known cost less to call than to
depend on.

Contract sources: the published API reference plus the official SDK
(``TurboDocx/SDK``, ``packages/py-sdk/.../modules/sign.py``).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx

from .config import Settings
from .errors import TurboSignError

USER_AGENT = "TurboDocx API Client (turbosign-mcp)"

# Both prepare endpoints take recipients/fields as *stringified* JSON, whether
# the body is multipart or JSON. Getting this wrong is the single most likely
# integration mistake, so it happens in exactly one place.
_STRINGIFIED = ("recipients", "fields", "ccEmails")


def _describe(response: httpx.Response) -> TurboSignError:
    """Turn an HTTP error response into something an agent can act on."""
    status = response.status_code
    detail = ""
    try:
        body = response.json()
        if isinstance(body, dict):
            detail = str(
                body.get("message") or body.get("error") or body.get("detail") or ""
            )
        # end if
    except ValueError:
        detail = (response.text or "").strip()[:300]
    # end try

    suffix = f" TurboSign said: {detail}" if detail else ""

    if status == 401:
        return TurboSignError(
            f"TurboSign rejected the credentials (401).{suffix}",
            "Check the API key and organization id with turbosign_whoami(), "
            "then re-run turbosign_configure() with a fresh key.",
        )
    # end if
    if status == 403:
        return TurboSignError(
            f"That account is not allowed to do this (403).{suffix}",
            "The key may lack TurboSign permissions or the plan may not "
            "include e-signature. Check the account at the TurboDocx console.",
        )
    # end if
    if status == 404:
        return TurboSignError(
            f"TurboSign has no such document (404).{suffix}",
            "Check the document_id. A voided or expired document may also "
            "read as missing.",
        )
    # end if
    if status == 400 and "senderemail" in detail.replace(" ", "").lower():
        return TurboSignError(
            f"TurboSign requires a sender email (400).{suffix}",
            "Set one with turbosign_configure(sender_email=...) or the "
            "TURBODOCX_SENDER_EMAIL environment variable.",
        )
    # end if
    if status in (400, 422):
        return TurboSignError(
            f"TurboSign rejected the request ({status}).{suffix}",
            "Check recipient addresses and field positions. "
            "turbosign_review() shows the result without emailing anyone.",
        )
    # end if
    if status == 429:
        retry = response.headers.get("retry-after", "")
        return TurboSignError(
            f"Rate limited by TurboSign (429).{suffix}",
            f"Wait {retry or 'a moment'} and try again.",
        )
    # end if
    return TurboSignError(
        f"TurboSign returned {status}.{suffix}",
        "This is usually transient — retry once. If it persists, check the "
        "TurboDocx status page.",
    )
# end def


class TurboSignClient:
    """Synchronous client over the TurboSign REST surface.

    Synchronous on purpose — see the README section "Why these tools are
    synchronous". Every call is bounded by ``settings.timeout``.
    """

    def __init__(self, settings: Settings) -> None:
        settings.require()
        self.settings = settings
    # end def

    # -- plumbing ---------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.api_key}",
            "x-rapiddocx-org-id": self.settings.org_id or "",
            "User-Agent": USER_AGENT,
        }
    # end def

    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        url = self.settings.base_url.rstrip("/") + path
        try:
            with httpx.Client(timeout=self.settings.timeout) as client:
                response = client.request(
                    method, url, headers=self._headers(), **kwargs
                )
        except httpx.TimeoutException as exc:
            raise TurboSignError(
                f"TurboSign did not respond within {self.settings.timeout:.0f}s.",
                "Large uploads take longer — retry, or raise TURBOSIGN_TIMEOUT.",
            ) from exc
        except httpx.HTTPError as exc:
            raise TurboSignError(
                f"Could not reach TurboSign at {url}: {exc}",
                "Check network access from this machine and that "
                "TURBODOCX_BASE_URL is right.",
            ) from exc
        # end try

        if response.status_code >= 400:
            raise _describe(response)
        # end if

        if not response.content:
            return {}
        # end if
        try:
            body = response.json()
        except ValueError:
            return {"raw": response.text}
        # end try
        return body if isinstance(body, dict) else {"data": body}
    # end def

    @staticmethod
    def _payload(
        recipients: list[dict],
        fields: list[dict],
        document_name: str | None,
        document_description: str | None,
        sender_email: str,
        sender_name: str | None,
        cc_emails: list[str] | None,
    ) -> dict[str, str]:
        """Build the shared body for both prepare endpoints."""
        payload: dict[str, str] = {
            "recipients": json.dumps(recipients),
            "fields": json.dumps(fields),
            "senderEmail": sender_email,
        }
        if document_name:
            payload["documentName"] = document_name[:255]
        # end if
        if document_description:
            payload["documentDescription"] = document_description[:1000]
        # end if
        if sender_name:
            payload["senderName"] = sender_name
        # end if
        if cc_emails:
            payload["ccEmails"] = json.dumps(cc_emails)
        # end if
        return payload
    # end def

    def _prepare(
        self,
        path: str,
        *,
        recipients: list[dict],
        fields: list[dict],
        content: bytes | None = None,
        filename: str | None = None,
        file_link: str | None = None,
        document_name: str | None = None,
        document_description: str | None = None,
        sender_email: str | None = None,
        sender_name: str | None = None,
        cc_emails: list[str] | None = None,
    ) -> dict:
        payload = self._payload(
            recipients,
            fields,
            document_name,
            document_description,
            # No fallback to the configured sender. tools/signing.py requires
            # both from the caller before we get here; falling back would put a
            # months-old config value on a contract nobody chose it for.
            sender_email or "",
            sender_name,
            cc_emails,
        )

        if content is not None:
            files = {"file": (filename or "document.pdf", content, "application/pdf")}
            return self._request("POST", path, data=payload, files=files)
        # end if

        if file_link:
            payload["fileLink"] = file_link
        # end if
        return self._request("POST", path, json=payload)
    # end def

    # -- endpoints --------------------------------------------------------

    def prepare_for_signing(self, **kwargs: Any) -> dict:
        """POST /turbosign/single/prepare-for-signing — sends the emails."""
        return self._prepare("/turbosign/single/prepare-for-signing", **kwargs)
    # end def

    def prepare_for_review(self, **kwargs: Any) -> dict:
        """POST /turbosign/single/prepare-for-review — no emails, returns a preview."""
        return self._prepare("/turbosign/single/prepare-for-review", **kwargs)
    # end def

    def get_status(self, document_id: str) -> dict:
        """GET /turbosign/documents/{id}/status."""
        return self._request("GET", f"/turbosign/documents/{document_id}/status")
    # end def

    def get_download_url(self, document_id: str) -> str:
        """GET /turbosign/documents/{id}/download — returns a presigned URL."""
        body = self._request("GET", f"/turbosign/documents/{document_id}/download")
        url = body.get("downloadUrl") or (body.get("data") or {}).get("downloadUrl")
        if not url:
            raise TurboSignError(
                "TurboSign did not return a download URL for that document.",
                "Check turbosign_status() — only completed documents can be "
                "downloaded.",
            )
        # end if
        return url
    # end def

    def fetch_signed(self, download_url: str) -> bytes:
        """Fetch the signed PDF from the presigned URL (expires after an hour)."""
        try:
            with httpx.Client(timeout=self.settings.timeout) as client:
                response = client.get(download_url)
        except httpx.HTTPError as exc:
            raise TurboSignError(
                f"Could not fetch the signed document: {exc}",
                "The presigned link expires an hour after it is issued — "
                "call turbosign_download() again for a fresh one.",
            ) from exc
        # end try
        if response.status_code >= 400:
            raise TurboSignError(
                f"The signed-document link returned {response.status_code}.",
                "Presigned links expire after an hour; request a new one.",
            )
        # end if
        return response.content
    # end def

    def void(self, document_id: str, reason: str) -> dict:
        """POST /turbosign/documents/{id}/void."""
        return self._request(
            "POST",
            f"/turbosign/documents/{document_id}/void",
            json={"reason": reason},
        )
    # end def

    def resend(self, document_id: str, recipient_ids: list[str]) -> dict:
        """POST /turbosign/documents/{id}/resend-email."""
        return self._request(
            "POST",
            f"/turbosign/documents/{document_id}/resend-email",
            json={"recipientIds": recipient_ids},
        )
    # end def

    def audit_trail(self, document_id: str) -> dict:
        """GET /turbosign/documents/{id}/audit-trail."""
        return self._request("GET", f"/turbosign/documents/{document_id}/audit-trail")
    # end def

    def probe(self) -> tuple[bool, str]:
        """Check whether these credentials actually work.

        Asks for the status of a well-formed but nonexistent document id. A
        working key gets 404 (no such document); a bad key gets 401 before the
        lookup happens. Cheap, and it creates nothing.

        The 401-vs-404 split is the assumption this rests on — see
        docs/VERIFICATION.md. Anything unexpected is reported honestly rather
        than guessed at, so a wrong assumption shows up as a clear message
        instead of a silent false pass.
        """
        probe_id = str(uuid.UUID(int=0))
        try:
            self.get_status(probe_id)
        except TurboSignError as exc:
            message = exc.message
            if "404" in message:
                return True, "Credentials accepted."
            # end if
            if "401" in message or "403" in message:
                return False, message
            # end if
            return False, f"Could not verify the credentials: {message}"
        # end try
        # A 200 for the all-zero uuid would be surprising, but it still proves
        # the credentials were accepted.
        return True, "Credentials accepted."
    # end def
# end class
