# Changelog

What changed, for the person using this — not the person reading git history.

## Unreleased

**You can send to anyone again.** The signer allowlist is gone.

It required every counterparty to be pre-approved in an environment variable
before you could send them anything, which meant signing an agreement with
somebody new was a job on the box rather than a thing you just did. The idea
was to bound who a hijacked agent could send a binding document to — but if you
send someone a document *to sign*, sending it is what permission means, and on
an agent deployment the send already stops for human approval anyway.

Nothing else changed. Names are still explicit, the sender is still stated on
every send, and the document still has to say where each party signs.

## Unreleased

**Anchors are now the only way a signature gets placed, and the server teaches
you how to write them.**

Roughly ten signatures landed in the wrong place on a real agreement before it
was corrected by hand. Every one was a position worked out by something that
could not see the page. So the guessing is gone: no `placement` argument, no
coordinates, no `fields` array. The document carries `{Signature1}` /`{Date1}`
tokens where each party signs, or the request is refused.

Ask for `get_instructions()` and you now get the layout that actually works —
anchor above the signature rule (TurboSign draws downward, so an anchor on the
rule pushes the signature below it), coloured white so nobody sees it, signature
left and date right, and the number matching the signer's position in your
recipients list rather than their position on the page. A document with no
anchors gets that same guidance back in the error, and if it already prints
"Signature: ______" somewhere the error says so and tells you to put the anchors
there.

**The catch, stated plainly:** a PDF you cannot edit can no longer be sent.
Anchors have to be real text, so they go into the source document and you
re-export.

**Nothing about a signer is defaulted any more.** `sender_email` and
`sender_name` are required by the tool schema itself, so a caller cannot leave
them out and inherit a months-old config value; every recipient needs an
explicit name and address.

## Unreleased

### The signing chain must be stated, never inferred — BREAKING

A signature request names the parties to a legal instrument. Every convenience
that let one of those names arrive by default was a way for the wrong person to
end up on a contract without anyone choosing it — and where an agent drives this
server, "nobody chose it" includes "the model chose it".

Four things changed, and each closes a different hole.

**Names are explicit.** A bare address is refused instead of being given a name
derived from its local part. `ann.jones@example.com` used to become "Ann Jones";
nobody decided that, and on an executed agreement it is the name of a party.
Pass `"Ann Jones <ann.jones@example.com>"` or a JSON array with names.

**The sender is per-send.** `sender_email` and `sender_name` are now required
arguments and no longer fall back to the configured values. The reply-to on a
signature request is where a counterparty's objection lands; it should be a
decision visible in the call, not a value inherited from a config file written
months ago.

**Signers must be on an allowlist.** Set `TURBOSIGN_ALLOWED_SIGNERS` to the
addresses or domains permitted to sign — `"@yourcompany.com, counsel@example.com"`.
Read from the environment only, so a tool call cannot widen it. An unset
allowlist refuses everything rather than allowing everything: reading absence as
permission is how a channel becomes a command channel.

This is the check that sees a lookalike domain. A well-formed name tells you
nothing about whether `bob@acme-invoices.com` belongs on the agreement.

**The document declares the chain.** Anchors are cross-checked against the
recipients: every recipient must have a field. The server already refused more
anchors than recipients; the reverse — an extra party on a contract whose
signature blocks do not mention them — is the direction an agent could produce,
and that party would receive the email with nothing to sign.

This is the only declaration in a request that the caller did not write at the
moment of sending. It is in the document a human drafted.

**Consequently, geometry placement is gone.** `placement="auto"` no longer falls
back to measuring the page, and `placement="coordinates"` is refused by name. A
document with no anchors declares nothing about who signs it, so there is
nothing to check the recipient list against. Documents need `{Signature1}`-style
tokens — which also gives exact field placement rather than boxes guessed at the
foot of the last page.

`turbosign_review` is held to every one of these rules. A rehearsal that skipped
validation would return a clean preview for a request that could never be sent,
which is worse than no rehearsal because it reads as approval.

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
