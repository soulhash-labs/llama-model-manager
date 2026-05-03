# Context MCP + Gateway Fix Plan (Final)

Date: 2026-05-03
Repo: /opt/llama-model-manager-v2.1.0

## Goal

Fix the context retrieval pipeline so:
1. `ctx_index` requests actually perform indexing through the bridge
2. Natural-language `ctx_search` queries return results when FTS matches zero rows but substring would match
3. Gateway `retrieve_context()` returns non-empty `context` for normal project questions
4. Fresh installs always build `context-mode-mcp` correctly (no missing `domino` or `dist/index.js`)

---

## Root Causes (Verified Against Code)

### 1. Bridge ignores `tool` field (`scripts/context_mcp_bridge.py`)
- `main()` reads request JSON but never checks `gateway_request.get("tool")`
- Always calls MCP `tools/call` with `name: "ctx_search"` (lines 153-167)
- If no `query` in request, returns `{"context": "", "items": []}` and exits 0
- A `{"tool": "ctx_index", ...}` request silently falls through the empty path

### 2. FTS zero-hit gap (`integrations/context-mode-mcp/src/db/search.ts`)
- `searchChunks()` runs FTS5 when `caps.fts5` is true (line 178)
- If FTS5 returns zero rows, the function returns empty `rows: []` (line 266-277)
- The substring fallback path (line 280+) only runs when `caps.fts5` is false
- Natural-language prompts produce zero FTS matches even when relevant chunks exist

### 3. Installer skips MCP build (`install.sh`)
- `install.sh` copies `integrations/context-mode-mcp/` but does not run `npm ci` or `npm run build`
- Fresh installs get source files but no `dist/index.js`
- `node_modules` may be stale or missing on new machines

---

## Fix Strategy (4 Phases)

### Phase 1: Fix Bridge Tool Dispatch
**File:** `scripts/context_mcp_bridge.py`

Replace `main()` with tool-aware dispatch:

```python
def main() -> int:
    gateway_request = read_stdin_json()
    tool = str(gateway_request.get("tool", "ctx_search")).strip() or "ctx_search"
    print(f"[BRIDGE] Tool: {tool}", file=sys.stderr)

    if tool == "ctx_index":
        return _dispatch_index(gateway_request)
    elif tool == "ctx_search":
        return _dispatch_search(gateway_request)
    else:
        print(json.dumps({"error": f"Unsupported tool: {tool}"}), file=sys.stderr)
        return 1
```

**`_dispatch_search(gateway_request)` — replaces existing logic:**
- Requires non-empty `query`; returns `{"context": "", "items": []}` if missing
- Spawns MCP server, sends `initialize` + `tools/call` with `name: "ctx_search"`
- Uses `extract_context()` for response parsing (existing function, no change needed)

**`_dispatch_index(gateway_request)` — new:**
- Extracts `title`, `markdown`, `uri`, `tags` from request
- Spawns MCP server, sends `initialize` + `tools/call` with `name: "ctx_index"`
- Passes `arguments` derived from request fields
- Returns structured MCP response via `extract_context()` or direct structuredContent passthrough
- Returns exit code 0 on success, 1 on failure

### Phase 2: Fix FTS Zero-Hit Fallback
**File:** `integrations/context-mode-mcp/src/db/search.ts`

After the FTS5 block (around line 266), detect zero-hit and fall back:

```typescript
// After ranked = rows.slice(0, safeLimit).map(...)
if (ranked.length === 0 && terms.length > 0) {
  console.log("[SEARCH] FTS5 returned 0 hits → substring fallback");
  return substringFallback(db, query, terms, safeLimit);
}
```

**Extract existing substring logic (lines 280-331) into `substringFallback()` helper:**
```typescript
function substringFallback(
  db: SqlBackend,
  query: string,
  terms: string[],
  safeLimit: number,
): { strategy: string; degraded: boolean; rows: SearchDoc[]; debug: Record<string, unknown> } {
  // Move lines 280-318 here (LIKE query, scoring, ranking)
  // Return with:
  //   strategy: "substring_fallback"
  //   degraded: true
  //   rows: ranked
  //   debug: { ...debug, fallback: true }
}
```

**Metadata behavior:**
- `strategy: "substring_fallback"` — distinguishable from raw `"substring"` (no FTS at all)
- `degraded: true` — truthful, FTS was available but yielded nothing

### Phase 3: Rebuild Context Mode MCP
**Path:** `integrations/context-mode-mcp`

```bash
cd integrations/context-mode-mcp
npm ci --omit=optional --ignore-scripts --no-audit --fund=false
npm run build
```

Verify `dist/index.js` exists and is newer than source files.

### Phase 4: Installer-Level MCP Setup
**File:** `install.sh`

Add this block near the end of the install process (after main integrations copy, before final success message):

```bash
# === Context Mode MCP Setup ===
echo "→ Setting up Context Mode MCP (required for context + GlyphOS)..."
cd "$APP_ROOT/integrations/context-mode-mcp"

# Clean previous state to avoid stale builds
rm -rf node_modules package-lock.json dist 2>/dev/null || true

# Fresh install + build
npm ci --omit=optional --ignore-scripts --no-audit --fund=false || npm install
npm run build

if [ -f "dist/index.js" ]; then
    echo "→ Context Mode MCP ready (dist/index.js built)"
else
    echo "⚠️  Context Mode MCP build failed — continuing anyway"
fi
```

**Why this matters:**
- Guarantees `domino` and all deps are installed on every fresh LMM install
- `dist/index.js` is always rebuilt from current source
- No more `Cannot find package 'domino'` errors on new machines
- `--omit=optional` is correct here (no optional platform deps needed)

---

## Verification Matrix

### Direct Bridge Tests
| Command | Expected |
|---------|----------|
| `echo '{"tool":"ctx_index","uri":"/tmp/test","title":"test"}' \| python3 scripts/context_mcp_bridge.py` | Structured response with `ok: true`, not `{"context":"","items":[]}` |
| `echo '{"tool":"ctx_search","query":"python","limit":5}' \| python3 scripts/context_mcp_bridge.py` | Non-empty `results` with `meta.strategy` |
| `echo '{"tool":"ctx_search","query":"List the main Python files in this project","limit":5}' \| python3 scripts/context_mcp_bridge.py` | Non-empty `results` (substring fallback), `meta.strategy: "substring_fallback"`, `meta.degraded: true` |

### Gateway E2E Test
```bash
cd /opt/llama-model-manager-v2.1.0
python3 -c '
import json, os
os.chdir("/home/angelo/smart_reader/v3")  # known-good indexed project
os.environ["LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE"] = "1"
from glyphos_openai_gateway import retrieve_context
result = retrieve_context(
    {"messages": [{"role": "user", "content": "test"}]},
    "List the main Python files in this project and what they do",
    model="test", stream=False
)
print(json.dumps(result, indent=2))
'
```

**Expected:** `status: "retrieved"`, `used: true`, non-empty `context`, `search_strategy: "substring_fallback"` or `"rrf"`.

---

## Files Changed

| File | Change | Risk |
|------|--------|------|
| `scripts/context_mcp_bridge.py` | Tool dispatch + `_dispatch_index` + `_dispatch_search` | Low — isolated module |
| `integrations/context-mode-mcp/src/db/search.ts` | FTS zero-hit → `substringFallback()` | Medium — search path change |
| `integrations/context-mode-mcp/dist/index.js` | Rebuilt artifact | None — generated |
| `install.sh` | MCP setup block at end of install | Low — additive, non-breaking |

---

## Execution Order

1. Patch `context_mcp_bridge.py` → verify direct `ctx_index` bridge call
2. Patch `src/db/search.ts` → rebuild MCP → verify direct `ctx_search` bridge call with natural language
3. Patch `install.sh` → verify install flow
4. Run gateway E2E test with `retrieve_context()`

---

## Deferred

| Item | Reason |
|------|--------|
| Anthropic `/v1/messages` proxy | Requires `BaseHTTPRequestHandler` changes, not Flask routes. Separate PR. |
| OpenClaw `/v1/completions` proxy | Same — needs stdlib handler modifications. Separate PR. |

---

## Acceptance Criteria

1. Bridge dispatches `ctx_index` and `ctx_search` correctly based on `tool` field
2. `ctx_index` bridge call returns real structured MCP response
3. Natural-language search returns non-empty results when substring fallback triggers
4. Metadata truthfully reflects execution path (`strategy: "substring_fallback"`, `degraded: true`)
5. Fresh `install.sh` builds `dist/index.js` successfully
6. Gateway `retrieve_context()` returns `status: "retrieved"` with non-empty `context` for project questions
