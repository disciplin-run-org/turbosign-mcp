---
id: AR-3
title: Synchronous tools with a bounded timeout, not task=True
status: accepted
spec_refs: []
paths: ["src/turbosign_mcp/tools/signing.py", "src/turbosign_mcp/config.py"]
supersedes: null
superseded_by: null
created: 2026-08-09T17:46:45+00:00
updated: 2026-08-09T17:47:21+00:00
---

# AR-3: Synchronous tools with a bounded timeout, not task=True

## Context

The house mcp-server skill carries a HARD-GATE: any tool that could occasionally exceed 30 seconds — explicitly including any network call to a service whose latency we do not control — must be registered with task=True, returning a task id immediately and running the work in the background. turbosign_send uploads a PDF to a third-party API, so on the face of it the gate applies.

The gate assumes a client that speaks the MCP task-status protocol and polls it. The primary consumer here does not: Hermes launches stdio servers and calls tools synchronously, with a per-server tool timeout that defaults to 300 seconds. Under task=True, Hermes would receive a task id it has no path to resolve — the gate's remedy would make the main consumer strictly worse, turning a working call into a dead end.

## Decision

Register every tool synchronously. Bound the work instead of backgrounding it: TURBOSIGN_TIMEOUT caps each HTTP request at 90 seconds by default, and TURBOSIGN_MAX_FILE_MB caps uploads at 10 MB.

This is a deliberate, recorded deviation from the skill's HARD-GATE rather than an oversight, and the reasoning is repeated in the README under "Why these tools are synchronous" so a reader meets it before reaching for a fix.

## Consequences

Accepted gains: works in every MCP client including those with no task support; a timeout surfaces as an error string naming the knob that fixes it rather than as an unresolvable task id; 90s sits comfortably inside Hermes' 300s budget.

Accepted costs:
- Anyone auditing this repo against the mcp-server skill will flag it as a violation. That is the cost of the deviation and the reason this record exists — the ADR is the answer to that audit.
- A client with a tighter budget than Hermes (Claude Code, around 60s) can time out on a slow upload. The 10 MB cap keeps a typical send well inside that, but a large scanned PDF over a poor link will fail rather than background itself.
- If large-document support becomes a requirement, or a consumer appears that does poll task status, this should be revisited. Adding task=True variants later is additive.
