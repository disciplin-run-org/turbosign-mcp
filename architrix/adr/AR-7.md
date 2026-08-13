---
id: AR-7
title: The signer allowlist is removed
status: accepted
spec_refs: []
paths: ["src/turbosign_mcp/chain.py", "src/turbosign_mcp/tools/signing.py", "src/turbosign_mcp/server.py"]
supersedes: AR-5
superseded_by: null
created: 2026-08-13T21:42:34+00:00
updated: 2026-08-13T21:42:52+00:00
---

# AR-7: The signer allowlist is removed

## Context

AR-5 rule 3 required every recipient to match TURBOSIGN_ALLOWED_SIGNERS, read from the environment, with an unset list refusing everything. It was the strongest of that ADR's four rules on paper: correctly implemented, and the only one that catches a fully named stranger at a lookalike domain, which no amount of naming discipline can see.

It was also the one that stopped the product working. Signing an agreement with somebody new — a departing shareholder, a new contractor, a counterparty's counsel — required an operator to edit a vault file on the box and re-provision before the send could happen. That is the ordinary case for this product, not an exception, so the allowlist charged a permanent everyday cost.

The argument that settles it was made in the revert PR against v1.0.0: if you send someone a document TO SIGN, sending it is what permission means. The allowlist asked the initiator to declare, in advance and out of band, that the person they are about to send a contract to is allowed to receive a contract.

The threat it addressed is real but narrower than it looked: an agent manipulated into sending a binding document to an attacker-controlled address. On the deployment that matters, turbosign_send sits behind an approvals.deny gate — a human presses send, and that human is the person who decided to send. The allowlist was defence-in-depth behind a control that already stops the bad outcome, bought at the price of the product's main use case.

## Decision

Remove the signer allowlist. Deleted: require_allowed_signers, load_allowlist, parse_allowlist, the TURBOSIGN_ALLOWED_SIGNERS environment variable, and its wiring in the Hermes deployment.

AR-5's other three rules stand and are restated here as the chain in force:

1. NAMES ARE EXPLICIT. A bare address is refused rather than given a name derived from its local part.
2. THE SENDER IS PER-SEND. sender_email and sender_name are required arguments in the tool schema, with no fallback to configuration.
3. THE DOCUMENT DECLARES THE CHAIN. Anchors are cross-checked against the recipients in both directions — a party with no signature block, or a signature block with no party, is refused. Extended by AR-6, which makes anchors the only placement mechanism.

This supersedes AR-5 rather than amending it, because the count of rules and the claim that they are complementary both change.

## Consequences

Accepted gains: the product does the thing it exists for. A counterparty who has never been sent anything before can be sent an agreement, which is the normal case. One less environment variable that is load-bearing, silent when missing, and indistinguishable from a misconfiguration.

Accepted costs, and they are real:
- A lookalike domain is no longer caught by the server. bob@acme-invoices.com now depends on a human reading the address on the approval prompt, and a human reading an approval prompt is exactly who misses a hyphen. This is the protection that was given up; nothing else here replaces it.
- An agent-driven send is bounded only by the approval gate. Where a deployment runs turbosign_send WITHOUT human approval, there is now nothing between a manipulated agent and a binding document. Any such deployment should reconsider, and the MCP instructions continue to tell hosts to gate send.

If the allowlist is proposed again — and it will be, because on paper it is the strongest rule here — the question to answer first is what it costs to add a new counterparty, and whether the deployment gates sends. Those two answers, not the threat model, are what decide it. This ADR exists so that argument starts from the record rather than from scratch.
