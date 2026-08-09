# turbosign-mcp

Send PDFs out for signature by asking for it.

```
> send ~/contracts/nda.pdf to Bob Smith <bob@example.com> for signature
```

A thin [MCP](https://modelcontextprotocol.io) server over the
[TurboSign](https://docs.turbodocx.com/docs/TurboSign/API%20Signatures/)
e-signature API. It speaks **stdio**, so any MCP client can launch it — Claude
Code, Hermes Agent, anything else — with no container, no port, and no daemon.

## What it does

| Tool | |
|---|---|
| `turbosign_send` | Send a document for signature. Emails the recipients. |
| `turbosign_review` | Same, but emails nobody and returns a preview URL. |
| `turbosign_status` | Has anyone signed yet? |
| `turbosign_download` | Fetch the completed signed PDF. |
| `turbosign_void` | Cancel a request that has not completed. |
| `turbosign_resend` | Chase a recipient. |
| `turbosign_audit_trail` | Hash-chained history — prepared, sent, viewed, signed. |
| `turbosign_setup` / `turbosign_configure` / `turbosign_whoami` | Getting a machine credentialled. |

## Install

```bash
git clone https://github.com/disciplin-run-org/turbosign-mcp
cd turbosign-mcp
python3 -m venv .venv
.venv/bin/pip install -e .
```

Then point your MCP client at it. For Claude Code, the bundled `.mcp.json`
already does this:

```json
{
  "mcpServers": {
    "turbosign": { "command": ".venv/bin/turbosign-mcp" }
  }
}
```

Use an absolute path to `.venv/bin/turbosign-mcp` if your client does not
resolve relative commands from the project directory.

## Getting credentialled

Ask the agent where to start:

```
> turbosign_setup()
```

It reports what is missing and gives you the URL to create a TurboDocx account
and the navigation to the API key. Then save the key one of two ways.

**From a terminal — the key never enters the conversation:**

```bash
.venv/bin/turbosign-mcp configure
```

Prompts for the key with the echo off, verifies it against the live API, and
writes it owner-only to `~/.turbosign-mcp/credentials.json`. Nothing is printed
but a masked fingerprint. Use this for any key you would mind seeing in a log.

There is deliberately **no `--api-key` flag**: a secret on a command line is
recorded in your shell history and is visible to every other user on the
machine via `ps`. Passing one is refused with an explanation rather than
silently ignored. For automated provisioning use `--api-key-file`, and
`--org-id` / `--sender-email` to skip the prompts.

**Or through the agent, if convenience wins:**

```
> turbosign_configure(api_key="...", org_id="...", sender_email="you@example.com")
```

Same verification, same store. The trade-off is that the key travels through
the agent's context and lands in that conversation's transcript on disk — fine
for a scoped key on a test account, not fine for a long-lived one or for a
session token that can do everything your user can.

Either way the credentials are **checked against the live API before they are
saved**, so a mistyped key fails at setup rather than on your first real send.
The server re-reads the store on every call, so there is nothing to restart.

`turbosign_whoami()` shows which account a machine is sending as — worth having
when the server is installed on several machines with different accounts.

### Credentials never live in this repo

The store is at `~/.turbosign-mcp/credentials.json` — **outside the working
tree**, so a credential cannot be committed by accident even if `.gitignore`
were wrong. `.gitignore` covers `credentials.json`, `.env`, `*.pem` and `*.key`
anyway, for the case where someone puts one in the tree deliberately. The test
suite needs no credentials, and its fixtures are obviously fake.

As a backstop that does not depend on anyone being careful, this repo has
GitHub **secret scanning and push protection enabled** — a push carrying a
recognised key pattern is rejected rather than published.

### Credentials resolve in this order

1. `TURBODOCX_*` environment variables
2. `~/.turbosign-mcp/credentials.json`
3. Neither — the server still runs and still offers the setup tools

**The environment always wins.** On an unattended box where the harness injects
the key, it never passes through the agent's context and no tool call can
overwrite it. `turbosign_configure` is the interactive path for a machine
someone is sitting at.

The trade-off, stated plainly: anything you pass to `turbosign_configure`
travels through the agent's context and, on a supervised agent, across its
approval surface. That is fine for interactive setup. For unattended
instances, prefer the environment.

## Testing: there is no sandbox

TurboSign has exactly one environment, and it is production. There is no test
host, no sandbox key and no dry-run flag — the "free sandbox" on the vendor's
marketing page means the free tier (5 signatures a month) on the live API. Every
`turbosign_send` reaches a real inbox, lands in a real audit trail, and cannot
be recalled, only voided.

So the server provides the rehearsal the API does not. Work up this ladder on
any new machine, new document layout, or new account:

| | | Emails anyone? |
|---|---|---|
| 1 | `turbosign_whoami(verify=True)` — credentials work, API reachable | No |
| 2 | `turbosign_review(...)` — same code path as send, preview URL back | No |
| 3 | `turbosign_send(...)` **to your own address first** | Yes |

Rung 2 is the important one: it uploads the document, parses the recipients,
places the fields and passes the API's own validation — everything a send does
except the send. Open the preview URL and look at where the boxes landed.

These instructions ship inside the server, so any MCP client that reads
`get_instructions()` gets them too, not just readers of this file.

**If you are embedding this server in an agent host**, gate `turbosign_send`
behind human approval, and consider gating `turbosign_void` as well —
cancelling someone's pending signature request is equally irreversible. Leave
`turbosign_review` ungated: it is the safe rehearsal, and gating it removes the
reason to prefer it.

## Where the signature boxes go

By default (`placement="auto"`) the server reads the PDF and decides:

- **Anchors, if the document has them.** Text like `{Signature1}`, `{Date1}` or
  `{Initial2}` is replaced in place by TurboSign. The trailing digit picks the
  recipient. Exact placement, no geometry involved.
- **Geometry, if it does not.** A signature and date box per recipient at the
  foot of the last page.

So a document authored with anchors gets exact placement for free, and an
arbitrary PDF still works. The response always reports which strategy was used.

Override with `placement="anchor"` (fail rather than fall back),
`placement="coordinates"`, or pass a `fields` array for full control.

### Anchors leave their token in the executed PDF

TurboSign paints over an anchor and draws the field on top, so nobody sees
`{Signature1}` on screen or on paper. But **the token is still in the text
layer of the finished contract**:

```
   Signature:  {Signature1}
   Date:  {Date1}
```

It reaches copy-paste, search indexes, a document-management system's full-text
extract, and screen readers.

**There is no way to avoid this while using anchors.** Making the token white
or 1pt does not help — text extraction ignores colour and size, so pypdf, a
search index and a screen reader all still find it. It only ever changed how
the *source* looked, and TurboSign already covers the token in the output
anyway. And the token cannot simply be omitted, because the API locates the
field by extracting that text.

So it is a genuine trade-off, not a technique problem:

| | Placement follows reflowed content | Clean text layer |
|---|---|---|
| **Anchors** (`{Signature1}`) | Yes | No — token survives |
| **Coordinates / explicit `fields`** | No — fixed geometry | Yes — no markers at all |

For a contract where the text layer matters — anything indexed, archived, or
read aloud — use `placement="coordinates"` or supply `fields` directly. Nothing
is written into the document, so nothing can leak out of it.

Verified on a real executed document, 2026-08-02.

### Date format is an account setting, not an API parameter

Out of the box a `date` field renders `08/01/2026` for 1 August 2026 —
ambiguous to anyone who reads dates day-first. There is **no per-field
date-format parameter**: the field options are `type`, `required`,
`defaultValue`, `isReadonly`, `backgroundColor` and geometry, in the REST API
and in every official SDK.

**Change it in the TurboDocx console, under your account settings.** Richer
formats are available than the API docs suggest — including fully unambiguous
ones like `Saturday, August 1st, 2026`. Set it once and every subsequent
signature uses it.

Two consequences worth knowing:

- **It is a property of the sending account, not the request.** Every document
  that account sends gets that format, and this server cannot override it per
  send. If you run several machines with different TurboDocx accounts, set the
  format on each one, or they will not match.
- **It is not retroactive.** Verified: re-downloading an already-executed
  document after changing the setting returns a byte-identical file. The
  format is baked in at signing time.

If you cannot change the setting — someone else's account, say — spell the date
in the body of the agreement ("this 1st day of August, 2026") and let the field
date stand as the machine timestamp.

`turbosign_review()` takes the same arguments as `turbosign_send()` but emails
nobody and hands back a preview URL. Worth doing the first time you send a new
kind of document.

## Configuration

Every setting is optional; the three credentials are needed before a send.

| Variable | Default | |
|---|---|---|
| `TURBODOCX_API_KEY` | — | Bearer token |
| `TURBODOCX_ORG_ID` | — | `x-rapiddocx-org-id` header |
| `TURBODOCX_SENDER_EMAIL` | — | Reply-to; the API rejects sends without it |
| `TURBODOCX_SENDER_NAME` | API key's name | Shown in the request emails |
| `TURBODOCX_BASE_URL` | `https://api.turbodocx.com` | |
| `TURBODOCX_APP_URL` | `https://app.turbodocx.com` | Console, for `turbosign_setup` |
| `TURBODOCX_SIGNUP_URL` | `https://www.turbodocx.com` | |
| `TURBOSIGN_HOME` | `~/.turbosign-mcp` | Credential store location |
| `TURBOSIGN_ALLOWED_DIRS` | `$HOME` | Roots documents may be sent from |
| `TURBOSIGN_MAX_FILE_MB` | `10` | Upload cap |
| `TURBOSIGN_TIMEOUT` | `90` | Per-request timeout, seconds |

## Health

Stdio servers have no health endpoint, so:

```bash
.venv/bin/turbosign-mcp --selftest
```

It lists the registered tools and reports how the machine is configured.
**A machine with no credentials exits 0** — that is the normal state before
setup, not a fault.

## Notes for the curious

**Why stdio and not HTTP.** TurboSign is a stateless request/response API.
There is no long-lived session to keep warm, so a container, a port and a
health check would be pure overhead. The client launches the process; when it
exits, nothing is left behind.

**Why `httpx` directly and not `turbodocx-sdk`.** This server *is* the thin
wrapper. Stacking it on a second wrapper buys drift protection at the price of
a pre-1.0 dependency and someone else's error messages — and error messages are
most of the value here, because an agent recovers from a sentence and cannot
recover from a stack trace.

**Why the tools are synchronous.** The usual MCP advice for a call to an
external service is a background task the client polls. Stdio clients like
Hermes do not poll the MCP task protocol, so that would make the primary
consumer worse. Instead the calls are synchronous with a bounded timeout
(90s, inside Hermes' 300s per-tool budget) and a 10 MB upload cap that keeps a
typical send well inside the tighter ~60s budget of other clients.

**Coordinates are top-left origin** — `y` counts down from the top edge. That
is both documented ("Vertical position from top edge") and verified against the
live API, and it is isolated to one constant in `placement.py` so a future
change stays a one-line fix. See [docs/VERIFICATION.md](docs/VERIFICATION.md).

## Architecture decisions

The four decisions most likely to look like mistakes to a new reader are
recorded as MADR records in [`architrix/adr/`](architrix/adr/), in force as of
2026-08-09:

| | |
|---|---|
| [**AR-1**](architrix/adr/AR-1.md) | Stdio transport, not HTTP in a container |
| [**AR-2**](architrix/adr/AR-2.md) | Call the API with httpx directly, not the official SDK |
| [**AR-3**](architrix/adr/AR-3.md) | Synchronous tools with a bounded timeout, not `task=True` |
| [**AR-4**](architrix/adr/AR-4.md) | Environment beats stored credentials, and onboarding lives in the server |

Each records what was given up as well as what was gained. AR-3 in particular
is a deliberate, documented deviation from the house MCP-server standard —
read it before "fixing" the synchronous tools.

The `architrix/` directory is Architrix's namespace in this repository, per the
ecosystem's directory-ownership convention. Edit the records through Architrix
(`adr_create` / `adr_status` with `org="disciplin-run-org"`, then
`github_save`), not by hand — a hand-edit will be overwritten by the next save.

## Development

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

The suite runs without network access or credentials — HTTP is mocked with
`respx`, and PDF fixtures are generated in code rather than committed, so
nothing in this public repo can carry a real name or address.

## Licence

MIT.
