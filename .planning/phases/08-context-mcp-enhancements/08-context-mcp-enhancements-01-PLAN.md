# Plan 08-context-mcp-enhancements-01: Incremental Indexing + File-Watcher Auto-Index

## Context

The Context MCP pipeline is operational:
- Indexer scans ~80 files → ~1227 chunks across the codebase
- FTS5 search is working with `ctx_search` tool
- Auto-index triggers on first search if project not yet indexed
- Full re-scan required for any change (no delta detection)
- No filesystem watching — manual re-index or first-search trigger only

## Goals

1. **Incremental indexing** — git-aware re-indexing that only updates changed files instead of full re-scan
2. **File-watcher auto-index** — watch filesystem for changes and auto-reindex on save (like a local LSP index)

## Implementation Tasks

### Task 1: Incremental Indexing
- [ ] Add `ctx_index_incremental` tool to `context_mcp_server.py`
- [ ] Implement git-aware change detection using `git diff --name-only HEAD~1` or file mtime comparison
- [ ] Modify indexer to accept file list and only re-index those files
- [ ] Update FTS5 and chunks table: delete old chunks for changed files, insert new chunks
- [ ] Add `last_indexed` timestamp tracking per file in a new `indexed_files` table
- [ ] Wire `ctx_index_incremental` to re-index only files modified since last index

### Task 2: File-Watcher Auto-Index
- [ ] Add `watchdog` dependency to `requirements.txt`
- [ ] Create `context_file_watcher.py` with `FileSystemEventHandler` subclass
- [ ] Watch `.py`, `.js`, `.ts`, `.tsx`, `.md`, `.json` files in project root
- [ ] On file save: trigger incremental re-index for changed file
- [ ] Debounce rapid saves (500ms window) to avoid thundering herd
- [ ] Add `ctx_watcher_start` / `ctx_watcher_stop` tools to control watching
- [ ] Integrate watcher lifecycle with MCP server start/stop

## Success Criteria

- [ ] `ctx_index_incremental` only re-indexes files that changed since last full index
- [ ] Git-aware detection works: `git diff` and mtime fallback both functional
- [ ] File watcher detects saves and triggers re-index within 500ms
- [ ] FTS5 results reflect updated content immediately after re-index
- [ ] No full re-scan occurs during incremental or watcher-driven re-index
- [ ] Watcher can be started/stopped via MCP tools

## Dependencies

- Existing Context MCP pipeline (`context_mcp_server.py`, `context_indexer.py`)
- `watchdog` library for filesystem events
- `git` CLI available in environment (optional, falls back to mtime)
- FTS5 virtual table schema in `context_index.db`
