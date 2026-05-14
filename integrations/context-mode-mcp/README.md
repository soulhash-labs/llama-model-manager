# Context Mode MCP

Project-aware context for your AI coding workflows. Indexes project files, retrieves relevant context snippets, and injects them into your AI assistant's request flow.

This package is part of [Llama Model Manager](https://github.com/soulhash-labs/llama-model-manager).

## Quick start

```bash
cd integrations/context-mode-mcp
npm ci --omit=optional --ignore-scripts --no-audit --fund=false
npm run build
npm run lifecycle-matrix
```

## Available scripts

| Script | Purpose |
|---|---|
| `npm run typecheck` | Type-check without emitting (`tsc --noEmit`) |
| `npm run build` | Build MCP server and dashboard |
| `npm run build:mcp` | Build only the MCP server bundle |
| `npm run build:dashboard` | Build only the dashboard bundle |
| `npm run lifecycle-matrix` | Run the MCP lifecycle smoke test (doctor, execute, index, search, etc.) |

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `CTX_PROJECT_ROOT` | No | `process.cwd()` | Project root used for context resolution and path policy checks. Can also be set via `--project-root` CLI argument. |

## Rate limiting

This MCP server is intended for local stdio transport and is invoked by the local MCP host process. It does not expose an HTTP server or public network socket. For this reason, network-style request rate limiting is intentionally not implemented here.

If a future transport exposes this server over a network boundary, rate limiting and authentication must be added at that transport layer.

## Design

- All tool inputs are validated with Zod schemas via `.parse()` — invalid requests receive structured error responses.
- Database backend selection follows a graceful fallback chain: `better-sqlite3` (best performance) → `node:sqlite` → `bun:sqlite` → a no-op stub with a descriptive error message.
- Command execution (`ctx_execute`, `ctx_execute_file`) is guarded by a security policy system: `isCommandAllowed()` checks an allowlist of permitted commands, and `isPathAllowed()` restricts writes to permitted directories. Dangerous commands (`rm -rf`, `shutdown`, `mkfs`) and system paths (`/etc/`, `/usr/bin/`, `/boot/`) are denied by default.
- The MCP tool manifest is intentionally fixed — tool names are hardcoded because they are a published API surface. The `ToolRegistry` in `context-tools.ts` provides a type-safe enum for dispatching.
