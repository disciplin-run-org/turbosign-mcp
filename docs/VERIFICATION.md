# Live verification

Two things in this server rest on assumptions that the published TurboSign
documentation does not settle. Both are isolated to one place each, and both
are confirmed by a single live call. Do this once, when credentials are first
available, and record the answer here.

Status: **not yet run** — no live credentials at the time of writing.

---

## 1. Which corner is `y` measured from?

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

## 2. Does a bad key give 401 where a good key gives 404?

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
reject path works. What remains is the other half: that a **valid** key asking
for a nonexistent document gets 404 rather than something else. That needs a
working key.

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

## 3. Full end-to-end pass

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
