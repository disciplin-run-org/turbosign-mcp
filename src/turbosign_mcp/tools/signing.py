"""The signing tools — the seven TurboSign operations."""

from __future__ import annotations

from typing import Literal

from fastmcp import FastMCP

from ..api import TurboSignClient
from ..config import load_settings
from ..chain import require_allowed_signers, require_sender
from ..errors import TurboSignError
from ..files import resolve_document, resolve_output_path
from ..placement import resolve_fields
from ..recipients import parse_recipients


def _summarise(body: dict, strategy: str, sent: bool) -> dict:
    """Shape a prepare response into something worth putting in context."""
    people = []
    for entry in body.get("recipients") or []:
        if isinstance(entry, dict):
            people.append(
                {
                    "id": entry.get("id"),
                    "name": entry.get("name"),
                    "email": entry.get("email"),
                    "signingOrder": entry.get("signingOrder"),
                }
            )
        # end if
    # end for

    out = {
        "ok": True,
        "document_id": body.get("documentId"),
        "status": body.get("status"),
        "placement": strategy,
        "recipients": people,
        "emails_sent": sent,
    }
    if body.get("previewUrl"):
        out["preview_url"] = body["previewUrl"]
    # end if
    if body.get("message"):
        out["message"] = body["message"]
    # end if
    return out
# end def


def _trim_audit_entry(entry: dict, max_message: int = 240) -> dict:
    """Flatten one audit entry down to what actually answers a question.

    The recipient an action concerns is NOT at the top level — the top-level
    ``recipient`` key is null on every entry the API returns. It lives at
    ``details.recipientInfo``, and ``details.message`` is the human sentence
    ("...email sent to Jesper Test (test@jurcenoks.com)"). Reading only the top
    level made this tool answer "who was emailed?" with null, which is the one
    question it exists to answer.

    Found by using it: a two-signer sequencing test where the trimmed output
    said recipient=null while the raw payload named the recipient outright.
    """
    details = entry.get("details") if isinstance(entry.get("details"), dict) else {}
    recipient_info = details.get("recipientInfo")
    if not isinstance(recipient_info, dict):
        recipient_info = entry.get("recipient")
    # end if
    if not isinstance(recipient_info, dict):
        recipient_info = {}
    # end if

    message = details.get("message")
    if isinstance(message, str) and len(message) > max_message:
        message = message[:max_message].rstrip() + "..."
    # end if

    out = {
        "actionType": entry.get("actionType"),
        "timestamp": entry.get("timestamp"),
        "user": (entry.get("user") or {}).get("email"),
        "recipient": recipient_info.get("email"),
        "recipient_name": recipient_info.get("name"),
    }
    if message:
        out["message"] = message
    # end if
    return {k: v for k, v in out.items() if v is not None}
# end def


def _prepare_args(
    file_path: str,
    recipients,
    document_name: str,
    document_description: str,
    sequential: bool,
    cc_emails,
    sender_email: str,
    sender_name: str,
):
    """Shared argument handling for the two prepare endpoints."""
    settings = load_settings()
    settings.require()

    # The chain rules run BEFORE the document is read, so a rejected request
    # costs nothing and the error names the actual problem rather than whatever
    # the PDF parser hit first.
    #
    # Both turbosign_send and turbosign_review come through here, deliberately:
    # a rehearsal that skipped the checks would not be a rehearsal.
    require_sender(sender_email, sender_name)

    path = resolve_document(file_path, settings)
    content = path.read_bytes()

    people = parse_recipients(recipients, sequential=sequential)
    require_allowed_signers(people)
    built_fields, strategy = resolve_fields(content, path.name, people)

    cc: list[str] | None = None
    if cc_emails:
        cc = (
            [e.strip() for e in cc_emails.split(",") if e.strip()]
            if isinstance(cc_emails, str)
            else list(cc_emails)
        )
    # end if

    return (
        settings,
        strategy,
        {
            "recipients": people,
            "fields": built_fields,
            "content": content,
            "filename": path.name,
            "document_name": document_name or path.stem,
            "document_description": document_description or None,
            "sender_email": sender_email or None,
            "sender_name": sender_name or None,
            "cc_emails": cc,
        },
    )
# end def


def register_tools(mcp: FastMCP) -> None:
    """Register the signing tools."""

    @mcp.tool
    def turbosign_send(
        file_path: str,
        recipients: str,
        sender_email: str,
        sender_name: str,
        document_name: str = "",
        document_description: str = "",
        sequential: bool = False,
        cc_emails: str = "",
    ) -> dict:
        """Send a document out for signature. This emails the recipients.

        THERE IS NO SANDBOX — TurboSign has one environment and it is
        production. This reaches a real inbox and cannot be recalled, only
        voided. Run turbosign_review() first; it takes these exact arguments
        and emails nobody.

        THE DOCUMENT SAYS WHERE PEOPLE SIGN. It must carry inline text anchors
        — {Signature1}, {Date1}, {Signature2}, {Date2} — placed where each
        party signs. There is no placement argument and no coordinates: a PDF
        with no anchors is refused rather than guessed at. Call
        get_instructions() for the layout that works, including putting the
        anchor above the signature rule and colouring it white.

        file_path: absolute path to a PDF that already contains the anchors.
        recipients: "Bob Smith <bob@example.com>, Ann Jones <ann@example.com>".
            Every recipient needs a name and an address; nothing is defaulted.
            Recipient N in this list signs at {SignatureN}/{DateN}.
        sender_email / sender_name: required, every time. Never taken from
            configuration — the reply-to on a binding request is a per-send
            decision.
        sequential: false (default) lets everyone sign at once; true makes
            them sign in the order listed.

        Returns the document_id — keep it, every other tool needs it.
        """
        try:
            settings, strategy, kwargs = _prepare_args(
                file_path, recipients, document_name, document_description,
                sequential, cc_emails, sender_email, sender_name,
            )
            body = TurboSignClient(settings).prepare_for_signing(**kwargs)
        except TurboSignError as exc:
            return exc.as_result()
        # end try
        return _summarise(body, strategy, sent=True)
    # end def

    @mcp.tool
    def turbosign_review(
        file_path: str,
        recipients: str,
        sender_email: str,
        sender_name: str,
        document_name: str = "",
        document_description: str = "",
        sequential: bool = False,
        cc_emails: str = "",
    ) -> dict:
        """Prepare a document and get a preview URL WITHOUT emailing anyone.

        Same arguments as turbosign_send, and held to the same rules — a
        rehearsal that skipped the checks would not be a rehearsal.

        Open the returned preview_url and LOOK at where each signature landed
        before sending. Anchors put the field where the author put the token,
        so a mistake here is a mistake in the document, and this is where you
        catch it: a wrong anchor number swaps who signs where and the document
        still sends perfectly happily.
        """
        try:
            settings, strategy, kwargs = _prepare_args(
                file_path, recipients, document_name, document_description,
                sequential, cc_emails, sender_email, sender_name,
            )
            body = TurboSignClient(settings).prepare_for_review(**kwargs)
        except TurboSignError as exc:
            return exc.as_result()
        # end try
        return _summarise(body, strategy, sent=False)
    # end def

    @mcp.tool
    def turbosign_status(document_id: str) -> dict:
        """Check where a signature request has got to.

        Reports the document's state (pending, completed, voided) and, where
        the API returns them, each recipient's state and id. The recipient ids
        are what turbosign_resend() needs.
        """
        try:
            body = TurboSignClient(load_settings()).get_status(document_id)
        except TurboSignError as exc:
            return exc.as_result()
        # end try
        data = body.get("data") if isinstance(body.get("data"), dict) else body
        return {"ok": True, "document_id": document_id, **data}
    # end def

    @mcp.tool
    def turbosign_download(document_id: str, output_path: str) -> dict:
        """Download a completed signed document to a local file.

        Only completed documents can be downloaded. output_path must be an
        absolute path in an existing directory.
        """
        try:
            settings = load_settings()
            target = resolve_output_path(output_path, settings)
            client = TurboSignClient(settings)
            content = client.fetch_signed(client.get_download_url(document_id))
            target.write_bytes(content)
        except TurboSignError as exc:
            return exc.as_result()
        except OSError as exc:
            return TurboSignError(
                f"Could not write the signed document: {exc}",
                "Check the directory is writable.",
            ).as_result()
        # end try
        return {
            "ok": True,
            "document_id": document_id,
            "saved_to": str(target),
            "bytes": len(content),
        }
    # end def

    @mcp.tool
    def turbosign_void(document_id: str, reason: str) -> dict:
        """Cancel a signature request that has not completed.

        The reason is recorded in the audit trail and is required. This cannot
        be undone — send the document again if you need to restart.
        """
        if not reason.strip():
            return TurboSignError(
                "A reason is required to void a document.",
                "Say why, for example 'superseded by a revised version'.",
            ).as_result()
        # end if
        try:
            body = TurboSignClient(load_settings()).void(document_id, reason.strip())
        except TurboSignError as exc:
            return exc.as_result()
        # end try
        data = body.get("data") if isinstance(body.get("data"), dict) else body
        return {"ok": True, "document_id": document_id, **data}
    # end def

    @mcp.tool
    def turbosign_resend(document_id: str, recipient_ids: str) -> dict:
        """Resend the signature request email to recipients who have not signed.

        recipient_ids is a comma-separated list of recipient UUIDs — get them
        from turbosign_status(). Only recipients whose turn it is in the
        signing order will actually be emailed.
        """
        ids = [r.strip() for r in recipient_ids.split(",") if r.strip()]
        if not ids:
            return TurboSignError(
                "No recipient ids were given.",
                "Call turbosign_status(document_id) to get them.",
            ).as_result()
        # end if
        try:
            body = TurboSignClient(load_settings()).resend(document_id, ids)
        except TurboSignError as exc:
            return exc.as_result()
        # end try
        data = body.get("data") if isinstance(body.get("data"), dict) else body
        return {"ok": True, "document_id": document_id, **data}
    # end def

    @mcp.tool
    def turbosign_audit_trail(document_id: str, limit: int = 50) -> dict:
        """Get the tamper-evident history of a document.

        Returns hash-chained entries — prepared, sent, viewed, signed, voided —
        newest last. Use this to answer "has Bob opened it yet?".
        """
        try:
            body = TurboSignClient(load_settings()).audit_trail(document_id)
        except TurboSignError as exc:
            return exc.as_result()
        # end try

        data = body.get("data") if isinstance(body.get("data"), dict) else body
        entries = data.get("auditTrail") or []
        trimmed = [
            _trim_audit_entry(e)
            for e in entries[-max(1, limit):]
            if isinstance(e, dict)
        ]
        return {
            "ok": True,
            "document_id": document_id,
            "document": data.get("document"),
            "entries": trimmed,
            "total_entries": len(entries),
            "truncated": len(entries) > len(trimmed),
        }
    # end def

    return
# end def
