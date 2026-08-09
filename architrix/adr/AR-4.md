---
id: AR-4
title: Environment beats stored credentials, and onboarding lives in the server
status: accepted
spec_refs: []
paths: ["src/turbosign_mcp/credentials.py", "src/turbosign_mcp/config.py", "src/turbosign_mcp/cli.py", "src/turbosign_mcp/tools/onboarding.py"]
supersedes: null
superseded_by: null
created: 2026-08-09T17:47:03+00:00
updated: 2026-08-09T17:47:26+00:00
---

# AR-4: Environment beats stored credentials, and onboarding lives in the server

## Context

This server installs on several machines, each with its own TurboDocx account and sender identity, and those machines have opposite needs.

An unattended box — a Hermes instance with the key injected by the harness — must have its identity fixed by whoever provisioned it, and must not be re-pointable by the agent running on it. An interactive box should be able to go from nothing to sending without anyone hand-editing a JSON file, because "edit this file first" is exactly the friction that leaves a machine uncredentialled.

A third constraint cuts across both: anything passed to an MCP tool travels through the agent's context and is written to that conversation's transcript on disk. For a scoped test key that is an acceptable trade; for a long-lived key, or a session token carrying the user's full authority, it is not.

## Decision

Resolve credentials in the order environment variables, then a per-machine store at $TURBOSIGN_HOME/credentials.json (0600), then unset. The environment always wins.

Onboarding is part of the product rather than a README step: turbosign_setup reports what is missing and where to get it, turbosign_configure saves it, turbosign_whoami reports which account this machine sends as. Credentials are verified against the live API before anything is persisted, so a mistyped key fails at setup rather than on a first real send.

For keys that must not enter a conversation, `turbosign-mcp configure` performs the identical operation from a terminal with a hidden prompt. There is deliberately no --api-key flag: a secret in argv is recorded in shell history and visible to other users via ps. Both paths build their candidate through config.candidate_settings() so they cannot drift on what "verify before save" means.

An unconfigured machine is a healthy state: the server still starts and still lists every tool, because a server that cannot boot cannot offer the tools needed to fix it.

## Consequences

Accepted gains: a managed box's identity cannot be changed by a tool call, so the ${env:} route stays authoritative on Hermes; a fresh machine self-provisions; a wrong key is rejected at setup; the store lives outside the working tree so a credential cannot be committed even if .gitignore were wrong.

Accepted costs:
- Two code paths (MCP tool and CLI) must stay in agreement. Mitigated by the shared candidate_settings() helper, but it remains a place where drift is possible.
- Precedence is invisible unless reported. A stored key silently shadowed by an environment variable looks configured while not being the one in use, so both configure paths and turbosign_whoami report the source of every value explicitly.
- The store is machine-local and outside the repo, so a Hermes rebuild loses it unless ~/.turbosign-mcp is added to that instance's state backup. The environment route survives a rebuild for free; this is called out in docs/HERMES-INTEGRATION.md.
- Offering three credential routes (env, MCP tool, CLI) is more surface than one would be, and the choice has to be explained rather than assumed.
