---
id: AR-2
title: Call the API with httpx directly, not the official SDK
status: accepted
spec_refs: []
paths: ["src/turbosign_mcp/api.py", "src/turbosign_mcp/errors.py"]
supersedes: null
superseded_by: null
created: 2026-08-09T17:46:32+00:00
updated: 2026-08-09T17:47:14+00:00
---

# AR-2: Call the API with httpx directly, not the official SDK

## Context

TurboDocx publishes an official Python SDK, turbodocx-sdk, covering exactly the seven TurboSign endpoints this server needs. It is a thin async wrapper over httpx with only two runtime dependencies. Using it is the obvious default and would absorb endpoint drift upstream.

Two things weigh against it. First, this server IS the thin wrapper — putting it on top of a second wrapper means two layers to reason about and two places a behaviour can come from. Second, and more decisive: the SDK is pre-1.0 (0.6.1 at time of writing) and async-only, while the error surface an agent consumes is the actual product here. An agent recovers from a sentence that names the fix and cannot recover from someone else's exception type. The full wire contract was already in hand, extracted from the published reference and read directly from the SDK's own source, so calling the endpoints costs less than depending on them.

## Decision

Call the seven endpoints directly with a synchronous httpx.Client in src/turbosign_mcp/api.py. Do not depend on turbodocx-sdk.

Every HTTP status is mapped to a TurboSignError carrying a one-sentence message plus a hint naming the remedy — 401 points at turbosign_whoami, 400 SenderEmailRequired points at the sender_email argument, 404 explains that a voided document also reads as missing.

## Consequences

Accepted gains: no pre-1.0 dependency; full control of timeouts, multipart shaping and error text; a synchronous client matching the synchronous-tools decision without an async bridge; the dependency set stays at fastmcp, httpx, pypdf.

Accepted costs:
- Endpoint drift is ours. If TurboDocx moves a path we learn from a 404 in production rather than from a dependency upgrade. Mitigated by tests/test_api_contract.py, which pins the wire shape of every endpoint against a mocked transport — including the non-obvious rule that recipients and fields go up as stringified JSON even inside a multipart body.
- New TurboSign features arrive as work rather than as a version bump.
- Two undocumented behaviours had to be established empirically instead of read from a typed client: the coordinate origin and the 401-vs-404 split the credential probe depends on. Both are recorded in docs/VERIFICATION.md.
