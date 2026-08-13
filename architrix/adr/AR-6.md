---
id: AR-6
title: Inline text anchors are the only placement mechanism
status: accepted
spec_refs: []
paths: ["src/turbosign_mcp/placement.py", "src/turbosign_mcp/tools/signing.py", "src/turbosign_mcp/server.py"]
supersedes: null
superseded_by: null
created: 2026-08-13T21:20:39+00:00
updated: 2026-08-13T21:20:52+00:00
---

# AR-6: Inline text anchors are the only placement mechanism

## Context

Roughly ten signatures landed in the wrong place on a real agreement before the document was corrected by hand. Every one of those was a position computed by something that could not see the page — either this server measuring page geometry, or an agent supplying coordinates it had inferred.

That is the evidence that settles a question the earlier design got wrong in both directions. The original server placed fields geometrically at the foot of the last page when a document had no anchors, which produced signatures floating free of the signature block a reader expects to sign on. AR-5's fourth rule then refused unanchored documents, which read as friction — until the failure count came in. Being blocked is visible and annoying; a misplaced signature is invisible and reaches a counterparty.

AR-5 rule 4 also did not finish the job. It refused placement="coordinates" by name while leaving build_coordinate_fields importable, and that path was reachable: call the function, hand its output straight back as fields=, and get identical placement. The refusal was cosmetic.

## Decision

Inline text anchors in the document are the only way a field is placed. Removed entirely: the placement argument, the fields array, the anchor argument, build_coordinate_fields, page_geometry and the Y_ORIGIN constant. This is deliberately narrower than the TurboSign API itself allows.

A PDF carries {Signature1}/{Date1} tokens where each party signs, or the request is refused. Every recipient must be covered — a half-anchored document would otherwise send, and the omitted party would receive an agreement with nowhere to sign.

Because a refusal that does not teach is just a retry with the same input, the error returns the layout: anchor on its own line ABOVE the signature rule (TurboSign draws the field downward, so an anchor on the rule pushes the signature below it), coloured to the page background so it is invisible on the executed document, signature left and date right, and the anchor NUMBER keyed to the signer's position in the recipients list rather than their position on the page. Where the PDF already prints "Signature: ______", the error names what it found and says to put the anchors there.

That guidance is defined once, in placement.ANCHOR_GUIDANCE, and served both through the MCP instructions and through the error.

## Consequences

Accepted gains: a signature cannot be placed by anything that has not seen the page. An anchor cannot be off by a page or a hundred points, because the document's author put it where the signature goes. The class of failure that produced ten hand-corrections is closed rather than warned about.

Accepted costs, stated rather than hidden:
- A PDF you cannot edit cannot be sent through this server. Anchors have to be real extractable text, so they go into the source document and it is re-exported. There is no workaround and none is offered.
- Scanned documents cannot be sent at all — no text layer, no anchors.
- The anchor token survives in the text layer of the executed PDF. Colouring it white hides it visually but not from text extraction, search indexing or a screen reader. Verified: pypdf extracts {Signature1} from a finished, executed agreement. This is inherent to anchors and is the price of the mechanism.
- The number-to-signer mapping is a silent failure mode. A wrong number swaps who signs where and the document sends perfectly happily, so turbosign_review and looking at the preview remain load-bearing rather than optional.

Reversal is possible but should not be casual: restoring geometry means restoring the failure that motivated this, and the evidence is a count of real incidents rather than a theory.
