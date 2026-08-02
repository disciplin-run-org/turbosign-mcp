# Live verification

Two things in this server rest on assumptions that the published TurboSign
documentation does not settle. Both are isolated to one place each, and both
are confirmed by a single live call. Do this once, when credentials are first
available, and record the answer here.

Status: **all settled, 2026-08-01/02**, live against `api.turbodocx.com` with a
real key — coordinate origin, credential probe, and sequential signing. The two
original assumptions were right and needed no code change; the third question
arose during testing and is answered below. Remaining notes are observations
about the API's shape, not open risks.

### 3. Does `sequential=True` actually work? — CONFIRMED

**The worry.** Both prepare endpoints echo `signingOrder: null` for recipients
sent as `1` and `2`. TurboDocx's own documented response example shows
`"signingOrder": 1` echoed back, so this looked like the API discarding the
field — which would make `sequential=True` a silent lie, delivering to every
party at once on a contract meant to be signed in order.

**Result (2026-08-02): the order is honoured. The null is response-shaping
only.** Two independent confirmations:

- The console's assign-fields view shows the two recipients with their order,
  naming Party B as second.
- The audit trail of a real send records exactly **one**
  `email_notification_sent`, and it names Party A alone:

  ```
  "message": "Signature request notification email sent to
              Jesper Test (test@jurcenoks.com)"
  "recipientInfo": {"name": "Jesper Test", "email": "test@jurcenoks.com"}
  ```

  Party B was not emailed. Sequential delivery works.

**Do not "fix" the null.** It is what the API returns; the data behind it is
correct. Read the order back from the audit trail, not from the send response.

The same run confirmed anchor placement end to end —
`fieldsProcessed: 4`, with `{Signature1}` `{Date1}` `{Signature2}` `{Date2}`
each resolved on page 1.

### Open observations

- `status` comes back lowercase (`review_ready`, `under_review`) where the
  reference documents `REVIEW_READY`. Nothing compares status strings today;
  do not start without normalising the case.
- `turbosign_status` returns only `{"status": ...}` — no recipient array, so it
  cannot answer "who has signed". The audit trail is the only source for
  per-recipient state.
- The audit trail's top-level `recipient` key is null on **every** entry; the
  recipient an action concerns lives in `details.recipientInfo`. This bit once
  already — see the `_trim_audit_entry` docstring.

---

## 1. Which corner is `y` measured from? — CONFIRMED (and it was documented)

**Correction, 2026-08-02.** This was framed below as undocumented. It is
documented — the field-reference table gives `y` as "Vertical position from top
edge (pixels)" — just not on the TurboSign API page that covers everything else
about fields, which is where it was looked for. The empirical check agreed with
the documentation, so nothing behaved unexpectedly and no code changed; only
the claim that it was unknowable was wrong.

Note the docs say *pixels* where this server sends PDF points from pypdf's
mediabox. That is harmless: `build_coordinate_fields` also sends `pageWidth`
and `pageHeight`, so the server scales into whatever units it uses. Do not drop
those two fields on the grounds that they are optional.


**Result (2026-08-01):** top-left origin, as assumed. `Y_ORIGIN = "top"` is
correct and no code changed.

An unanchored test PDF was prepared with `turbosign_review` (no emails sent),
`placement` came back as `coordinates`, and the preview showed the signature
and date boxes at the **foot** of the last page, below a marker printed near
the bottom of the document — which is where a top-left origin puts them.

Preview: `https://app.turbodocx.com/e-signature/assign-fields/ad7adac7-5a32-4d7a-8b70-305e5eef394d`

The record below is kept for whoever has to re-run this after an API change.

**The assumption.** `placement.Y_ORIGIN = "top"` in
`src/turbosign_mcp/placement.py` — that `y` is the distance down from the top
edge of the page.

**Why it is uncertain.** The API reference gives only the validation rule
(`x + width <= pageWidth`, `y + height <= pageHeight`), which is satisfied by
either convention. PDF itself uses a bottom-left origin; web viewers, including
the kind of field editor TurboSign ships, normally use top-left. Nothing in the
docs or the official SDK says which one the API expects.

**How to settle it.** One call, no emails sent:

```
turbosign_review(
    file_path="/path/to/any/unanchored.pdf",
    recipients="You <you@example.com>",
)
```

Open the `preview_url` it returns and look at the last page.

| What you see | What it means | Action |
|---|---|---|
| Signature box near the **bottom** | Assumption correct | Change Status above to confirmed |
| Signature box near the **top** | Origin is bottom-left | Set `Y_ORIGIN = "bottom"` |

**If it needs changing:** edit the one constant in `placement.py`, and update
`test_the_y_origin_assumption_is_the_documented_one` and
`test_top_origin_puts_the_first_row_near_the_page_bottom` in
`tests/test_placement.py` to match. Nothing else depends on it.

---

## 2. Does a bad key give 401 where a good key gives 404? — CONFIRMED

**The assumption.** `TurboSignClient.probe()` in `src/turbosign_mcp/api.py`
verifies credentials by requesting the status of a well-formed but nonexistent
document id (the all-zero UUID). A working key should get 404 — no such
document — and a bad key should get 401 before the lookup happens.

**Why it is uncertain.** Undocumented. Some APIs return 404 for unauthorised
requests deliberately, to avoid confirming that a resource exists.

**Half of this is now confirmed** (2026-08-01, live against
`api.turbodocx.com`): an invalid key returns **401 Unauthorized**, not 404.

```
$ turbosign-mcp configure --api-key-file ... --org-id test-org --sender-email ...
Verifying against TurboSign...
error: those credentials were not accepted. TurboSign rejected the
credentials (401). TurboSign said: Unauthorized
  Nothing has been saved.
```

So the API does distinguish auth failure from a missing resource, and the
reject path works.

**The other half is now confirmed too** (2026-08-01, same host, with a real
key): `turbosign_whoami(verify=True)` returned `credentials_valid: true` and
"Credentials accepted." — the probe asked for the all-zero UUID, got a 404
rather than a 401, and read that correctly as "the key works, the document does
not exist".

```json
{"configured": true, "api_key": "****ba2d",
 "credentials_valid": true, "verification": "Credentials accepted."}
```

**Assumption 2 is settled: the probe is sound in both directions.** A bad key
is rejected and nothing is saved; a good key passes. No change needed.

**How to settle it.** With working credentials in place:

```
turbosign_whoami(verify=True)     # expect credentials_valid: true
```

Then deliberately break it:

```
turbosign_configure(api_key="obviously-wrong", org_id="...", sender_email="...")
```

Expect this to be **rejected** and nothing to be saved.

| Result | What it means | Action |
|---|---|---|
| Good key valid, bad key rejected | Assumption correct | Change Status above to confirmed |
| Bad key also reports valid | The API returns 404 for unauthorised too | Probe needs a different endpoint |

The failure mode is already handled honestly rather than silently: anything
other than a clean 404 or 401 is reported as "Could not verify the credentials"
rather than being guessed at. So a wrong assumption shows up as a visible
message, not a false pass. `test_an_unexpected_probe_result_is_reported_not_guessed`
covers that path.

---

## 4. Full end-to-end pass — DONE 2026-08-02

The whole lifecycle ran against the live API on a two-signer agreement, and
every tool in the server has now touched production at least once.

```
review    -> placement: anchor, no emails             ok
send      -> emails_sent: true, Party A only          ok
status    -> under_review -> completed                ok
sign      -> Party A, then Party B released           ok
download  -> 2,207,255 bytes, valid 1-page PDF        ok
audit     -> per-recipient entries, hash-chained      ok
void      -> status: voided, reason recorded          ok
```

Both parties received the executed agreement and a separate audit-trail PDF.
The rendered page shows both signatures on their intended lines, both dates
filled, and a per-field hash fingerprint under each — the anchors themselves
painted over and invisible.

**Two things learned from the executed document:**

1. **Anchor tokens survive in the text layer.** They are covered visually, but
   `{Signature1}` is still extractable from the finished contract, so it
   reaches copy-paste, search indexes and screen readers.

   An earlier draft of this file advised authoring anchors in white or 1pt
   text. That was wrong, and Jesper caught it: extraction ignores colour and
   size, so pypdf, a search index and a screen reader all still find the
   token. Nor can the token be omitted — the API locates the field by
   extracting exactly that text. **There is no way to use anchors and keep a
   clean text layer.** Where the text layer matters, use
   `placement="coordinates"` or explicit `fields`, which write nothing into
   the document at all. See the README for the trade-off table.

2. **Dates default to US-format** (`08/01/2026` for 1 August) and there is no
   per-field date-format parameter in the REST API or any official SDK.

   **Corrected 2026-08-02:** an earlier version of this file concluded the
   format could not be changed. It can — Jesper found the setting in the
   TurboDocx console under account settings, with richer options than the API
   docs describe, including `Saturday, August 1st, 2026`. The mistake was
   reasoning from the API surface and the published docs to a claim about the
   product. The API half was right; the conclusion was not.

   Two properties confirmed since:

   - **Not retroactive.** Re-downloading the already-executed test document
     after the setting changed returned a byte-identical file (same md5), so
     the format is baked in at signing time.
   - **Account-scoped, not request-scoped.** It applies to everything that
     account sends and this server cannot override it per document. Machines
     using different TurboDocx accounts need the setting applied to each.

   Still unverified: how the new format actually renders on a freshly signed
   document. That costs one signature to establish.

### The procedure, for re-running after an API change

Once the above are settled, run the whole lifecycle once against the live API:

1. `turbosign_review` on an unanchored PDF — check placement in the preview.
2. `turbosign_review` on a PDF containing `{Signature1}` — confirm the response
   reports `placement: "anchor"`.
3. `turbosign_send` to your own address.
4. `turbosign_status` — expect pending.
5. Sign it from the email.
6. `turbosign_status` — expect completed.
7. `turbosign_download` — open the PDF and confirm the signature is on it.
8. `turbosign_audit_trail` — confirm the viewed and signed entries.
9. `turbosign_send` a second document, then `turbosign_void` it with a reason.
10. Error paths: a bad document id, and a wrong API key. Both must come back as
    sentences with a usable hint, never a traceback.
