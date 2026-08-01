# Deploying turbosign-mcp to Hermes Agent

**Audience:** the session that owns the `Hermes` repo
(`~/PycharmProjects/Hermes`, `github.com/JesperJurcenoks/hermes-rh`).

This server was deliberately built without touching that repo — distribution is
yours. This document is the spec, not a summary: everything you need to wire it
up is here, and where a decision was already taken the reasoning is given so you
can overrule it knowingly rather than by accident.

Authoritative sources behind the claims below:
- `guest/config/config.yaml.tmpl` — the `mcp_servers` block, the `approvals`
  deny globs, and the `__ENV_PASSTHROUGH__` marker.
- `guest/steps/30-hermes-config.sh` — renders `config.yaml` and writes
  `~/.hermes/.env` from `guest/config/secrets.allowlist`.
- `guest/steps/40-gw-mcp.sh` — the existing MCP step, for shape.
- `lib/push-guest.sh` — how source trees reach the box.
- `guest/heal/heal.py`, `guest/upgrade/regression.py` — per-service checks.
- hermes-agent's own `website/docs/reference/mcp-config-reference.md` — the
  stdio server schema.

---

## 1. What is different about this one

Every MCP server Hermes runs today is either an npx stdio server or the
dockerised HTTP `google-workspace-mcp`. This is neither: it is a **Python stdio
server**, so there is **no container, no port, and no health URL**. Do not copy
`40-gw-mcp.sh` wholesale — most of it exists to manage a container.

The health check is `turbosign-mcp --selftest`, which exits 0 and prints the
tool list. **It exits 0 on a machine with no credentials**, by design: an
uncredentialled box is the normal state before setup, and a heal check that
goes red for that would cry wolf.

---

## 2. Getting the source onto the box

`config.env`:

```bash
TURBOSIGN_MCP_SRC="${TURBOSIGN_MCP_SRC:-${HOME}/PycharmProjects/disciplin-run/turbosign-mcp}"
```

`lib/push-guest.sh`, next to the `GW_MCP_SRC` block:

```bash
if [ -d "${TURBOSIGN_MCP_SRC}" ]; then
    echo "── pushing turbosign MCP source"
    SSH "mkdir -p ${GUEST_REPO}/turbosign-mcp"
    RSYNC --delete \
        --exclude '.git' --exclude '.venv/' --exclude '__pycache__/' \
        --exclude '.pytest_cache/' \
        "${TURBOSIGN_MCP_SRC}/" "${GUEST_USER}@${TARGET_IP}:${GUEST_REPO}/turbosign-mcp/"
else
    echo "WARN: TURBOSIGN_MCP_SRC=${TURBOSIGN_MCP_SRC} not found — turbosign MCP will be skipped." >&2
fi
```

Add `TURBOSIGN_MCP_ENABLE` to the `export` list in the provision call if you
want a per-profile switch.

## 3. The install step

New file, `guest/steps/41-turbosign-mcp.sh`. Short, because there is no
container:

```bash
#!/usr/bin/env bash
# 41-turbosign-mcp.sh — install the TurboSign stdio MCP server into its own
# venv. No container, no port: Hermes launches the process itself. Idempotent.
set -euo pipefail

: "${REPO_ROOT:?}"
SRC="${REPO_ROOT}/turbosign-mcp"
VENV="${HOME}/.hermes-mcp/turbosign"

if [ ! -d "${SRC}" ]; then
    echo "WARN: ${SRC} absent (TURBOSIGN_MCP_SRC not pushed) — skipping turbosign MCP."
    exit 0
fi

mkdir -p "$(dirname "${VENV}")"
[ -d "${VENV}" ] || python3 -m venv "${VENV}"
"${VENV}/bin/pip" install --quiet --upgrade pip
"${VENV}/bin/pip" install --quiet -e "${SRC}"

echo "· verifying"
"${VENV}/bin/turbosign-mcp" --selftest
echo "✓ turbosign MCP installed at ${VENV}"
```

The venv path `~/.hermes-mcp/turbosign/bin/turbosign-mcp` is what the config
block below launches. Keep them in step.

## 4. The config block

In `guest/config/config.yaml.tmpl`, under `mcp_servers:`:

```yaml
  turbosign:
    command: __GUEST_HOME__/.hermes-mcp/turbosign/bin/turbosign-mcp
    enabled: true
    timeout: 300
    env:
      TURBODOCX_API_KEY: "${env:TURBODOCX_API_KEY}"
      TURBODOCX_ORG_ID: "${env:TURBODOCX_ORG_ID}"
      TURBODOCX_SENDER_EMAIL: "${env:TURBODOCX_SENDER_EMAIL}"
      TURBODOCX_SENDER_NAME: "${env:TURBODOCX_SENDER_NAME}"
      TURBOSIGN_ALLOWED_DIRS: __GUEST_VAULT__
    tools:
      resources: false
      prompts: false
```

Notes:

- `${env:VAR}` is resolved by Hermes from `~/.hermes/.env`. This is the point of
  section 5 — it means `config.yaml` holds a *reference*, not the key itself.
- `timeout: 300` is the schema default; stated explicitly because uploads are
  the slow path and a future default change should not silently shorten it.
- `TURBOSIGN_ALLOWED_DIRS` scoped to the vault means the agent can only send
  documents that live in the vault. Widen deliberately if that is too tight.
- `resources: false` / `prompts: false` — the server exposes neither, so this
  just keeps four unused utility tools out of the agent's context.
- Add a `__GUEST_HOME__` substitution to `30-hermes-config.sh` if there is not
  one already; `__GUEST_VAULT__` is there today.

## 5. Keeping the key out of the agent's shell

**This is the part that needs a small change to Hermes itself, and it was
Jesper's explicit choice.**

Today `30-hermes-config.sh` reads `guest/config/secrets.allowlist` and uses it
for *two* things at once:

1. writing `~/.hermes/.env` (which is where `${env:VAR}` resolves from), and
2. building the `env_passthrough` block (which is what the agent's own shell
   and code tools can see).

So adding `TURBODOCX_API_KEY` to that one list would put the key in the agent's
shell environment as a side effect of making it available to the MCP
subprocess. The existing note at the bottom of `secrets.allowlist` — that
Google credentials live only inside the MCP container and never in the Hermes
process — is the same instinct; a container gave it for free, and stdio does
not.

**The change:** a second list, `guest/config/secrets.mcp-only`, whose keys go
into `~/.hermes/.env` but **not** into `env_passthrough`.

```
# secrets.mcp-only — written to ~/.hermes/.env so ${env:VAR} resolves in an
# mcp_servers entry, but deliberately NOT exposed to the agent's shell and
# code tools. For credentials a specific MCP server needs and nothing else.
TURBODOCX_API_KEY
TURBODOCX_ORG_ID
TURBODOCX_SENDER_EMAIL
TURBODOCX_SENDER_NAME
```

In `30-hermes-config.sh`, section 1 becomes two reads:

```bash
mapfile -t KEYS < <(sed -e 's/#.*//' "${CONFIG_DIR}/secrets.allowlist" | awk 'NF{print $1}')
MCP_ONLY=()
if [ -f "${CONFIG_DIR}/secrets.mcp-only" ]; then
    mapfile -t MCP_ONLY < <(sed -e 's/#.*//' "${CONFIG_DIR}/secrets.mcp-only" | awk 'NF{print $1}')
fi
```

Section 2 writes `.env` from **both** lists (`"${KEYS[@]}" "${MCP_ONLY[@]}"`).
Section 3 builds `env_passthrough` from `KEYS` only — unchanged.

Then put the actual values in `host-vault/secrets.env` as usual.

**What this does and does not buy.** The MCP subprocess gets the key; the
agent's shell does not see it in its environment. The agent can still read
`~/.hermes/.env` if it decides to `cat` the file — it runs as the same user, and
nothing short of a separate uid changes that. The gain is that the key is not
sitting in the environment of every shell command by default, which is the
difference between "reachable if the agent goes looking" and "present in every
tool invocation". That is worth having; it is not a sandbox, and the README
says so.

**The alternative Jesper rejected:** just add the keys to `secrets.allowlist`.
No Hermes change, but the key lands in `env_passthrough`.

**A third option, if you prefer no Hermes change at all:** leave the keys out of
both files and let the agent run `turbosign_setup()` / `turbosign_configure()`
once per box. The credentials then live in `~/.turbosign-mcp/credentials.json`
(0600) and never touch `config.yaml` or `.env`. The cost is that the key passes
through the agent's context during setup, and that a rebuild loses it unless
that path is in the state backup. Your call — the server supports all three.

## 6. The approval gate

`turbosign_send` emails a document to a third party and cannot be recalled,
only voided. It belongs with the other outward-send tools in the `approvals:`
`deny:` list in `config.yaml.tmpl`, alongside `*publish*` and `*send_campaign*`:

```yaml
    # Outward send — a signature request cannot be recalled, only voided.
    - "*turbosign_send*"
```

**Do not gate `turbosign_review`.** It is the same call with the emails
suppressed, and it exists precisely so the agent can check its work without
bothering you. Gating it would remove the reason to prefer it.

Consider also gating `turbosign_void` — cancelling someone's pending signature
request is destructive and irreversible. Left out of the list above because it
is a smaller blast radius than sending, but it is a defensible addition.

Note the tool name Hermes matches against is the registered name,
`turbosign_send` — the `mcp__turbosign__` prefix is applied for display, and
the deny globs are wildcarded at both ends anyway.

## 7. Heal and regression checks

`guest/heal/heal.py`, alongside `check_gw_mcp`:

```python
def check_turbosign_mcp():
    venv = os.path.expanduser("~/.hermes-mcp/turbosign/bin/turbosign-mcp")
    if not os.path.exists(venv):
        return ("turbosign MCP", False, False, "not installed")
    try:
        out = subprocess.run([venv, "--selftest"], capture_output=True,
                             text=True, timeout=60)
        ok = out.returncode == 0
        return ("turbosign MCP", False, ok, out.stdout.strip().splitlines()[-1])
    except Exception as exc:
        return ("turbosign MCP", False, False, str(exc))
```

and add it to the checks list. Same shape in
`guest/upgrade/regression.py` with `@check("turbosign MCP responds", critical=False)`.

**`--selftest` exits 0 on an uncredentialled machine.** If you want the check to
be stricter on an instance that is supposed to be credentialled, assert on the
`configured: yes` line in stdout rather than on the exit code — do not "fix"
the exit code, other callers depend on the current behaviour.

## 8. Verifying the deployment

On the box:

```bash
~/.hermes-mcp/turbosign/bin/turbosign-mcp --selftest     # 12 tools, exit 0
```

In the agent:

```
/reload-mcp
```

then ask it to call `turbosign_whoami()` — it should report the account and,
with `verify=True`, that the credentials were accepted. Then
`turbosign_review()` on a PDF in the vault, which emails nobody.

Before the first real send, read [VERIFICATION.md](VERIFICATION.md): the
coordinate-origin question there is settled by exactly that review call, and it
is worth settling on the first document rather than the first important one.

## 9. Which instances

Not decided here. `hermes-jj` (personal, 24/7) is the obvious candidate;
whether the Radical Honesty instance should be able to send signature requests
is a policy question, not a technical one. If only one instance should have it,
gate the step and the config block on a profile variable rather than shipping
it everywhere and relying on the approval prompt.
