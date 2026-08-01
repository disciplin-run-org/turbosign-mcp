# Changelog

What changed, for the person using this — not the person reading git history.

## 0.2.0 — 2026-08-01

First release. You can now send a PDF for signature by asking for it.

**Sending.** Point it at a PDF, name the recipients, and it goes:

```
send ~/contracts/nda.pdf to Bob Smith <bob@example.com> for signature
```

Recipients can be written the way you would write them in an email client —
`Bob Smith <bob@example.com>, ann@example.com`. Everyone can sign at once by
default, or in a set order if you ask for it.

**It works out where the signature goes.** If your PDF contains marker text
like `{Signature1}` or `{Date1}`, the boxes land exactly there. If it does not,
a signature and date box are placed for each recipient at the foot of the last
page. Either way it tells you which it did, so there is no guessing. You can
also give exact coordinates if you want them.

**Check before you send.** `turbosign_review` does everything a send does
except email anyone, and hands back a preview link so you can look at where the
boxes landed. Worth doing the first time you send a new kind of document.

**Tracking.** Check status, download the signed PDF when it is done, chase a
recipient who has not signed, cancel a request, or read the full audit trail of
who opened what and when.

**Setting up a machine.** No config file to edit. Ask for `turbosign_setup()`
and it tells you what is missing and where to go and get it; `turbosign_configure()`
checks the credentials against TurboSign before saving them, so a mistyped key
fails there rather than on your first real send. `turbosign_whoami()` tells you
which account a given machine sends as — useful when several machines each have
their own.

Credentials are stored owner-only, and environment variables always take
precedence over the saved ones, so a centrally-managed machine cannot have its
identity changed by a tool call.

**Known unknown.** One detail of the TurboSign API is undocumented — whether
vertical positions are measured from the top or the bottom of the page. This
release assumes the top. If your first preview shows the signature box at the
wrong end of the page, `docs/VERIFICATION.md` explains the one-line fix.
