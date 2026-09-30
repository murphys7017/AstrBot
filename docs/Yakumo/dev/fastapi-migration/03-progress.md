# FastAPI migration checkpoints

Implementation worktree: `codex/fastapi-migration`, based on `ffa462d10`.
Upstream reference: `26ff7673f`. Production ports 6185 and 6199 are reserved.

## Status

- P0: fixed baseline and per-route identity/auth inventory recorded in
  `legacy-contract.json` (235 HTTP method/path pairs, 3 WS); payload/response
  behavior remains owned by the existing handlers and will be retained.
- P1: native ASGI infrastructure input/output smoke passed, including request
  identity, body-size rejection and malformed JSON; production entry unchanged.
- P2: services wired to the native Dashboard host; existing HTTP tests passed.
- P3-P5: platform host, Pages UI and network acceptance still pending.

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

## Checkpoint 3: native Dashboard cutover

The branch now serves an actual FastAPI application through Hypercorn. Its
factory wires the existing Core and 25 service instances without initializing
another Core. Dashboard handlers use the native request context. Former server
attributes and route import aliases remain available to existing callers.
Dynamic plugin APIs and unified platform callbacks retain a bounded Quart
compatibility context; native and old response bodies still stream incrementally.
The v1 prefix is matched at a path boundary and remains API-Key-only.

Existing tests passed on the native host: Dashboard 48, external API-Key 11,
knowledge-base request contracts 5, platform response contracts 2. Adapted only
framework setup and old class monkeypatch targets, preserving assertions.
Corrected legacy response cleanup to use the Quart body context manager, native
query iteration/first multipart value, and lowercase ASGI test headers.
Live socket streaming, WS and browser acceptance remain pending; these HTTP
tests do not prove configured production platforms or AG99 delivery.

## Checkpoint 4: standalone webhook host and Pages route

Standalone Slack, QQ official, WeCom, WeCom AI and Weixin official-account
servers now use the bounded native ASGI host. Their existing `route`,
`add_url_rule`, `run_task` and request-body contracts remain available, while
platform-specific signature and plaintext response behavior stays in each
adapter. QQ signature/extra-data and platform response tests passed (8).

The frontend now registers `/plugin-page/:pluginName/:pageName`, matching the
existing embedded Pages view and sidebar links. The dashboard package build was
not run because this isolated worktree has no `dashboard/node_modules`.

## Checkpoint 5: isolated network smoke

An isolated Core and native Dashboard started on `127.0.0.1:6285` with this
worktree's data root. HTTP login returned 200 and a JWT; the authenticated
`/api/plugin/get` request returned 200. The temporary process was stopped after
the check. Production ports 6185/6199 and the original worktree were not
touched. This confirms native network serving only; WebSocket/SSE and browser
acceptance are still separate pending checks.

The same isolated host also accepted a JWT-authenticated WebSocket connection
on `127.0.0.1:6286/api/live_chat/ws`; the client connected and closed cleanly.
No chat payload or configured provider was invoked, so this is a transport and
authentication smoke rather than a full live-chat acceptance.

Frontend `pnpm typecheck` passed after installing the locked dependencies.
`pnpm build` reached Vite transformation but failed in the Windows temporary
esbuild cleanup with `Access is denied`; no TypeScript error was reported.
