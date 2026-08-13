---
id: AR-5
title: The signing chain is stated, never inferred
status: superseded
spec_refs: []
paths: ["src/turbosign_mcp/chain.py", "src/turbosign_mcp/recipients.py", "src/turbosign_mcp/tools/signing.py"]
supersedes: null
superseded_by: AR-7
created: 2026-08-13T21:20:15+00:00
updated: 2026-08-13T21:42:52+00:00
---

# AR-5: The signing chain is stated, never inferred

## Context

A signature request names the parties to a legal instrument. Every convenience that let one of those names arrive by default was a way for the wrong person to end up on a contract without anyone choosing it — and where an agent drives this server, "nobody chose it" includes "the model chose it".

Recorded after the fact: this shipped as v1.0.0 without an ADR, and the omission had a cost. The Hermes deployment pinned itself back to v0.5.4 because the new rules stopped its boxes sending, with no written decision to weigh that against. A decision this consequential needs to be arguable from a document rather than from a commit message.

## Decision

Four rules, checked before the document is read, so a rejected request costs nothing and the error names the real problem rather than whatever the PDF parser hit first. Both turbosign_send and turbosign_review are held to all four — a rehearsal that skipped the checks would not be a rehearsal.

1. NAMES ARE EXPLICIT. A bare address is refused rather than given a name derived from its local part.
2. THE SENDER IS PER-SEND. sender_email and sender_name are required arguments in the tool schema, with no fallback to configuration.
3. SIGNERS ARE ALLOWLISTED. TURBOSIGN_ALLOWED_SIGNERS, read from the environment only so a tool call cannot widen it. Unset refuses everything rather than allowing everything.
4. THE DOCUMENT DECLARES THE CHAIN. Anchors are cross-checked against the recipients; every recipient must have a field. Extended by AR-6.

## Consequences

Rule 3 is the one that earns its keep, and it is worth being clear that the others do not carry equal weight. Tested against the bypasses that matter: an allowlist of "@yourcompany.com" refuses bob@yourcompany.com.evil.com and bob@yourcompany.co. It is the only rule here that defends against an adversary rather than against sloppiness, and it is the one a human approving a send cannot perform by eye — a lookalike domain reads as correct.

Rules 1 and 2 are hygiene. They protect against a guessed name on an executed instrument and against a stale reply-to. Both are real, neither is an attack surface, and both cost the caller friction on every send. They sit behind a human approval gate in the deployment that matters, which lowers their marginal value further. Kept because the cost is small, not because the threat is large.

Accepted costs:
- An agent that has only an email address for a counterparty cannot send. It must obtain a name first.
- An unset allowlist is indistinguishable from a misconfigured one: both refuse. This is the correct direction to fail, and it did cost a production deployment its ability to send until the vault was populated.
- Every send carries two more required arguments.

The deployment cost was real and is recorded here rather than smoothed over: the Hermes instances ran the previous release for four days rather than adopt these rules, because the rules arrived without a written rationale to weigh.
