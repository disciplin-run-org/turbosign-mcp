# Changelog

What changed, for the person using this — not the person reading git history.

## Unreleased

**Verified end to end against the live service.** A real two-signer agreement
went out, was signed in order, came back executed and was downloaded — every
tool in the server has now been exercised against production, not just against
mocks. Sequential signing does what it says: Party B is not emailed until Party
A has signed.

Two practical findings from the executed contract, both now in the README:

- **Anchors leave their token in the finished PDF.** Nobody sees
  `{Signature1}` on screen or paper, but it is still in the text layer, so it
  reaches copy-paste, search indexes and screen readers. This cannot be
  avoided while using anchors — the API finds the field by extracting that
  exact text, and white or 1pt type does not help because extraction ignores
  colour and size. Where the text layer matters, use coordinate placement
  instead: it writes nothing into the document.
- **Dates default to US-format** (`08/01/2026` for 1 August), which is
  ambiguous to anyone who reads dates day-first. There is no date-format
  option on a field — but you can change it in the TurboDocx console under
  your account settings, where richer formats are available than the API docs
  describe, including `Saturday, August 1st, 2026`. It applies to everything
  that account sends, and it is not retroactive: documents already executed
  keep the format they were signed with.

Also fixed: the audit trail was reporting `recipient: null` on every entry, so
the tool meant to answer "has Bob opened it yet?" could not. It now names the
recipient and includes the API's own description of each action.

**A way to save your API key without it entering the conversation.**

```bash
turbosign-mcp configure
```

Prompts for the key with the echo off, checks it against the live API, and
writes it owner-only to `~/.turbosign-mcp/credentials.json`. Only a masked
fingerprint is ever printed. The MCP tool `turbosign_configure` still works and
is more convenient, but anything passed to it travels through the agent's
context and is written to that conversation's transcript on disk — fine for a
scoped key on a test account, not fine for a long-lived one.

There is no `--api-key` flag, on purpose: a secret on a command line lands in
your shell history and is visible to every other user on the machine through
`ps`. Passing one is refused with an explanation. Automated provisioning can
use `--api-key-file` instead, with `--org-id` and `--sender-email` to skip the
prompts.

If an environment variable is shadowing the key you just stored, it says so —
environment still wins, and a stored key that is being overridden looks
configured without being the one in use.


**There is no TurboSign sandbox, and the server now says so.** TurboSign runs
one environment: production. Every send reaches a real inbox and can only be
voided, never recalled. The server's built-in instructions now carry a
three-step test ladder — check credentials, rehearse with `turbosign_review`
which emails nobody, then send to your own address first — so any MCP client
that reads `get_instructions()` inherits it, not just people who read the
README. The warning is on the `turbosign_send` tool description too, for models
that never read the server instructions.

Agent hosts embedding this server are told to gate `turbosign_send` behind
human approval and leave `turbosign_review` open.

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

**Placement is verified, not assumed.** One detail of the TurboSign API is
undocumented — whether vertical positions are measured from the top or the
bottom of the page. It is the top, checked against the live API rather than
inferred: an unanchored test document put its signature and date boxes exactly
where intended, at the foot of the last page.
