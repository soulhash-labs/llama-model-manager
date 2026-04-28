# Context-Mode MCP (ACE Context Saturation Defense)

## Purpose
Context-Mode MCP is an optional integration under `integrations/context-mode-mcp` that reduces MCP context blowups by running tool execution in temporary work directories with allowlist/denylist policy checks, indexing large outputs, and returning compact snippets + IDs instead of raw payloads.

## Layout
- `integrations/context-mode-mcp/package.json`
- `integrations/context-mode-mcp/tsconfig.json`
- `integrations/context-mode-mcp/esbuild.config.ts`
- `integrations/context-mode-mcp/src/index.ts`
- `integrations/context-mode-mcp/src/tools/*.ts`
- `integrations/context-mode-mcp/src/db/*.ts`
- `integrations/context-mode-mcp/src/sandbox/*.ts`
- `integrations/context-mode-mcp/src/hooks/*`
- `integrations/context-mode-mcp/dashboard/` (React + Vite dashboard)
- `docs/CONTEXT_MODE_MCP.md`

## Runtime behavior
1. MCP process resolves context from `CTX_PROJECT_ROOT` or `process.cwd()`.
2. Project hash: `sha256(realpath(project_root)).slice(0,16)`.
3. DB path: `~/.claude/context-mode/sessions/<project-hash>.db`
4. Cache dir: `~/.claude/context-mode/cache/<project-hash>/`
5. DB open order:
   - `better-sqlite3`
   - `node:sqlite`
   - `bun:sqlite`
   - fallback to in-process unavailable backend
6. All tool runs are recorded in `runs` table.
7. `chunks` are indexed through required chunking rules:
   - split by `##` headings
   - preserve fenced code blocks
   - split oversized chunks by H3 sections before any fallback split

## Output policy
- Default response returns `stdout` inline for execute-like tools.
- Auto-index is triggered when:
  - `stdout_bytes > 50_000` always, or
  - `stdout_bytes > 5_000` and `intent` provided.
- Indexed mode returns snippets and index refs; raw dump is withheld.

## Search
- FTS path: `chunks_fts` (porter) and optional `chunks_fts_trigram`.
- If trigram unavailable, degraded mode is reported.
- RRF merges porter + trigram result ranks.
- Substring fallback for non-FTS installs.

## Hooks
- Hooks runner: `src/hooks/runner.ts`
- Template: `src/hooks/templates/claude-hooks.json`
- Implemented scripts:
  - `src/hooks/claude-pre-tool-use.sh`
  - `src/hooks/claude-post-tool-use.sh`
  - `src/hooks/claude-pre-compact.sh`
  - `src/hooks/claude-session-start.sh`
  - `src/hooks/not-yet-supported.sh`
- Pre-compact creates a bounded XML snapshot (`<= 2048` bytes) and indexes it into `source='events'`.

## Lifecycle guard
- Parent PID sampled on start.
- Poll every 30 seconds.
- Exit if parent PID becomes invalid.

## Tooling
All tools are defined in Zod-first schemas in `src/schemas/context-tools.ts`:
- `ctx_execute`
- `ctx_execute_file`
- `ctx_batch`
- `ctx_index`
- `ctx_search`
- `ctx_fetch_index`
- `ctx_stats`
- `ctx_doctor`
- `ctx_upgrade`
- `ctx_purge`
- `ctx_dashboard_open`

## Notes on degradation
- If hooks fail, they are treated as non-fatal and DB writes are guarded.
- If DB/FTS unavailable, tool behavior falls back to plain table scan or inline output and doctors report degraded flags.
- No API keys or secrets are stored by this integration.

## Lifecycle matrix (manual)
- Validate `ctx_upgrade` and `ctx_purge` directly:
  - `ctx_upgrade`:
    - `confirm=false` returns `DENIED` and performs no write.
    - `confirm=true, rebuild=true` re-runs schema initialization.
    - `reconfigure=true` rebuilds cache directory layout.
  - `ctx_purge`:
    - `confirm=false` returns `DENIED`.
    - `confirm=true` clears project docs/chunks/events rows and optional cache/db path cleanup.
  - Both tools include run telemetry in `runs` only when DB writes are still available.

## Automated lifecycle matrix
Run a full lifecycle matrix in one command from `integrations/context-mode-mcp`:

```bash
npm run lifecycle-matrix
```

The script checks:

- `ctx_doctor`
- `ctx_execute`
- `ctx_upgrade` (both deny path and confirm+rebuild+reconfigure path)
- `ctx_purge` (both deny path and confirm path)
- `ctx_index`
- `ctx_search`

## Dependency hygiene
- Non-blocking advisories observed during smoke verification (environment/localized):
  - `npm ci` may emit a high-severity advisory for transitive packages.
  - Engine warning from `@vitejs/plugin-react` can appear on older Node patch lines.
- These are flagged as hygiene items; they are not treated as functional regressions for context-mode-mcp behavior.
