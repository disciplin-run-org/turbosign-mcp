---
id: AR-1
title: Stdio transport, not HTTP in a container
status: proposed
spec_refs: []
paths: ["src/turbosign_mcp/server.py"]
supersedes: null
superseded_by: null
created: 2026-08-09T17:45:51+00:00
updated: 2026-08-09T17:45:51+00:00
---

# AR-1: Stdio transport, not HTTP in a container

## Context

Every other MCP server in this ecosystem runs FastMCP over streamable HTTP in a Docker container, on an allocated port, with a /health endpoint — that is what the house mcp-server skill prescribes and what leanspecs, iris-qa, quartermaster and google-workspace-mcp all do.

Three facts argue against copying it here. TurboSign is a stateless request/response REST API: there is no session to keep warm and no long-lived credential material to isolate in a volume. The primary consumer is Hermes Agent, which launches stdio MCP servers natively via command/args/env in its mcp_servers config, and treats HTTP servers as remote endpoints needing their own lifecycle. And google-workspace-mcp — the apparent precedent — is containerised because it isolates long-lived Google OAuth tokens in /data, not because MCP servers are containerised by default. Copying its shape for a stateless API buys a container, a port allocation, a compose file and a health probe in exchange for nothing.

## Decision

Run as a stdio server. FastMCP's mcp.run() default, launched by the client as a subprocess. No Dockerfile, no docker-compose service, no port, no HTTP health endpoint.

Health is a `--selftest` subcommand that enumerates the registered tools and reports how the machine is configured, exiting 0 on a machine with no credentials because that is the normal pre-setup state rather than a fault.

## Consequences

Accepted gains: nothing to deploy but a venv; the client owns the process lifecycle; no port to collide; identical behaviour under Claude Code and Hermes; a rebuild cannot leave a stale container running.

Accepted costs:
- shared.mcp.app_factory cannot be used — it returns a FastAPI app and is HTTP-only. The server's category (repo_agnostic) is therefore declared in the README rather than enforced at boot, losing the factory's boot-time contract validation.
- No HTTP health probe. Anything monitoring this server (Hermes heal.py, regression.py) must shell out to `--selftest` instead of curling /health, which is a different integration shape from every sibling service.
- The monorepo conventions for a service — a docker-compose entry and an allocated port — do not apply, so turbosign-mcp will look anomalous next to the other submodules.
- If a future consumer needs one shared long-lived instance rather than a subprocess per client, this must be revisited. Adding an HTTP entry point later is additive and would not invalidate the stdio path.
