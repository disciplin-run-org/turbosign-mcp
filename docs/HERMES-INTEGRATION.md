# Running turbosign-mcp under Hermes Agent

**Status: implemented and live.** This was written as a handover spec; the
Hermes session has since built it, in places differently and better. It is now
a record of how the integration actually works, and of what v2.0.0 requires
from it.

The wiring lives in the `Hermes` repo (`~/PycharmProjects/Hermes`), not here:

| | |
|---|---|
| `config.env` | `TURBOSIGN_ENABLE` (default `0`), `TURBOSIGN_REPO`, `TURBOSIGN_REF` |
| `profiles/hermes-rh.env`, `profiles/hermes-jj.env` | per-instance `TURBOSIGN_ENABLE="1"` |
| `guest/steps/41-turbosign-mcp.sh` | venv install, verified with `--version` |
| `guest/config/config.yaml.tmpl` | the `mcp_servers.turbosign` block and the `approvals.deny` entries |
| `guest/config/secrets.allowlist` | the `TURBODOCX_*` keys and `TURBOSIGN_ALLOWED_SIGNERS` |
| `guest/upgrade/regression.py` | health check |
| `tests/test_turbosign.py` | 15 tests asserting the above holds |

---

## What v2.0.0 requires, and what breaks without it

Two preconditions. A box missing either is installed, healthy, and unable to
send — which is the failure mode worth knowing about in advance.

**1. `TURBOSIGN_ALLOWED_SIGNERS` must be set in the instance's vault.** Unset
refuses every signer rather than allowing every signer. Present in both
`host-vault/` and `host-vault-jj/` as of 2026-08-13; re-check after any vault
rotation, because the symptom is "nothing can be sent" with correct-looking
config everywhere.

**2. Documents must carry `{Signature1}`/`{Date1}` anchors.** There is no
geometric fallback — an unanchored PDF is refused, not placed at the foot of
the page. The server's `get_instructions()` returns the layout, and so does the
error. See AR-6 in `architrix/adr/` for why, and the README for the layout.

The practical consequence for an agent: it cannot take a counterparty's PDF and
send it. Anchors are real extractable text, so they go into the source document
and it is re-exported.

## The pin

`TURBOSIGN_REF` is a tag, never `main`. Tracking a moving branch on a
dependency that sends legal documents is how an unreviewed change reaches
production.

It sat at `v0.5.4` from 2026-08-09 to 2026-08-13 because v1.0.0's chain rules
landed before their owner had reviewed them and stopped the boxes sending. That
was the right call with the information available, and it is the reason AR-5
exists: a decision of that weight needs a document to argue from, not a commit
message. Now `v2.0.0`.

## Two things the Hermes session got right that this spec had wrong

**A stdio MCP subprocess gets a filtered environment.** Neither
`~/.hermes/.env` nor `terminal.env_passthrough` reaches it — only what is
written in the server's own `env:` block. This spec originally proposed a
`secrets.mcp-only` list on the theory that `env_passthrough` would carry the
credentials to the subprocess. It would not have. The credentials were
hand-applied to `~/.hermes/config.yaml` on each box for some time before this
was understood, and every re-provision silently deleted them while reporting
success.

The working shape is a per-server `env:` block holding `${VAR}` references,
which Hermes interpolates from `~/.hermes/.env` at load time:

```yaml
  turbosign:
    command: __TURBOSIGN_BIN__
    enabled: true
    env:
      TURBODOCX_API_KEY: "${TURBODOCX_API_KEY}"
      TURBODOCX_ORG_ID: "${TURBODOCX_ORG_ID}"
      TURBODOCX_SENDER_EMAIL: "${TURBODOCX_SENDER_EMAIL}"
      TURBODOCX_SENDER_NAME: "${TURBODOCX_SENDER_NAME}"
      TURBOSIGN_ALLOWED_SIGNERS: "${TURBOSIGN_ALLOWED_SIGNERS}"
```

References rather than values, so the secret's only home is the vault and no
copy lands in `config.yaml`, which the agent can read. An unset variable stays
as the literal `${...}` — so TurboSign fails with a visibly wrong key instead
of authenticating as nobody in particular.

Note that `TURBODOCX_SENDER_EMAIL` and `_NAME` no longer influence a send:
since v1.0.0 the sender is a required per-call argument with no fallback to
configuration. They are harmless where they are.

**The block is dropped, not disabled.** When `TURBOSIGN_ENABLE` is not `1` the
whole `mcp_servers` entry is removed at render time rather than shipped
`enabled: false`, so a box never meant to send binding documents has no path to
it at all.

## The approval gate

Both irreversible tools are gated in `approvals.deny`:

```yaml
    - "*turbosign_send*"
    - "*turbosign_void*"
```

`turbosign_review` is deliberately absent. It is the rehearsal that uploads,
places the fields and returns a preview URL while emailing nobody — gating it
would remove the reason to prefer it over a real send.

Under v2.0.0 that rehearsal matters more, not less. Anchors put the field where
the author put the token, so a wrong anchor *number* swaps which party signs
which block and the document sends looking perfectly correct. The preview is
where that is caught.

## Health

Stdio has no health URL. The check is:

```bash
~/.hermes-mcp/turbosign/bin/turbosign-mcp --selftest
```

It exits 0 on a box with no credentials, because uncredentialled is the normal
state before setup rather than a fault. If you want a stricter check on an
instance that is supposed to be credentialled, assert on the `configured: yes`
line in stdout rather than changing the exit code — other callers depend on the
current behaviour.

## One setting that is not in any file here

Date rendering is configured in the TurboDocx console under account settings,
not through the API, and this server cannot set it per document. The default is
US-format (`08/01/2026`), ambiguous to a day-first reader; unambiguous formats
such as `Saturday, August 1st, 2026` are available there.

It is a property of the sending account, so **each instance's TurboDocx account
needs it set separately**, and it is not retroactive — already-executed
documents keep the format they were signed with.

## Which instances

Both `hermes-rh` and `hermes-jj` set `TURBOSIGN_ENABLE="1"`. The default in
`config.env` is `0`, so any future instance acquires the ability to send
binding documents because a profile says so, never by inheriting a default.
