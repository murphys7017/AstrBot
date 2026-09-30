# FastAPI migration checkpoints

Implementation worktree: `codex/fastapi-migration`, based on `ffa462d10`.
Upstream reference: `26ff7673f`. Production ports 6185 and 6199 are reserved.

## Status

- P0: fixed baseline and per-route identity/auth inventory recorded in
  `legacy-contract.json` (235 HTTP method/path pairs, 3 WS); payload/response
  behavior remains owned by the existing handlers and will be retained.
- P1: native ASGI infrastructure input/output smoke passed, including request
  identity, body-size rejection and malformed JSON; production entry unchanged.
- P2-P5: pending.

## Acceptance rules

Use an isolated `ASTRBOT_ROOT`, test-only configuration and loopback ports.
Never copy live credentials, enable production adapters, write production data,
or restart the original worktree. Record static, HTTP, network streaming,
browser and full platform acceptance separately. An unverified boundary is not
passing. Commit each coherent reviewed batch as requested by the user.

## Checkpoint 1: native infrastructure

Added FastAPI/Hypercorn/multipart dependencies and adapted the pinned upstream
request bridge. Legacy Quart response bodies are streamed, not accumulated;
stream iteration retains its request identity. WebSocket authentication runs
before acceptance, and incoming HTTP bodies are bounded while being read.
Ruff and an isolated native HTTP smoke passed. No production process was
started, stopped or modified. The repository ignores `uv.lock`; it was resolved
locally without adding the entire dependency lock as unrelated metadata.

## Checkpoint 2: routing/service extraction

Moved 25 business modules to `services/` and all their route declarations to
`api/`. Former `routes/` imports remain compatibility aliases, not duplicate
business implementations. The existing project-workspace DB service was kept.
Compared every moved Handler AST before formatting; only class/import names
and registration ownership changed. Six existing public boundary tests passed
on the still-Quart host: login, dynamic plugin API, scoped Pages assets and
non-default Profile SubAgent behavior. Ruff and whitespace checks passed.

The independent environment initially had a Windows `crypto`/`Crypto` casing
collision and a newer MCP major than production. Repaired only the migration
virtual environment and aligned MCP/Quart/FastAPI to the installed production
versions for comparable acceptance; the production environment was not changed.
