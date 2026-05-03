---
phase: 10-context-injection-tuning
plan: 03
type: execute
wave: 2
depends_on: ["10-context-injection-tuning-01"]
files_modified:
  - scripts/glyphos_openai_gateway.py
  - integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/glyph_to_prompt.py
autonomous: true
requirements:
  - CONTEXT-05

must_haves:
  truths:
    - "Gateway skips context block entirely when retrieval returns nothing"
    - "Gateway allows GE1-LINES but not GE1-JSON for degraded context"
    - "Gateway flags stale context but does not penalize quality score"
    - "Response headers indicate context status (empty/degraded/stale/available)"
  artifacts:
    - path: "scripts/glyphos_openai_gateway.py"
      provides: "Fallback logic for empty and degraded context"
      pattern: "context.*empty|context.*degraded|no context"
    - path: "integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/glyph_to_prompt.py"
      provides: "Prompt assembly handles empty context gracefully"
      pattern: "if.*context|context.*or.*None"
  key_links:
    - from: "scripts/glyphos_openai_gateway.py"
      to: "glyph_to_prompt.py"
      via: "Context block assembly with empty/degraded handling"
      pattern: "context_block|assemble.*prompt"
---

<objective>
Implement graceful fallback logic for when context retrieval returns empty or degraded results. Currently the pipeline may still attempt encoding on poor context or include empty context blocks. This plan ensures clean behavior at every degradation level.

Purpose: No more edge-case behavior when context is missing or poor quality.
Output: Fallback logic in gateway, updated prompt assembly, response headers for context status.
</objective>

<execution_context>
@/home/angelo/.config/opencode/get-shit-done/workflows/execute-plan.md
@/home/angelo/.config/opencode/get-shit-done/templates/summary.md
@.planning/ROADMAP.md
</execution_context>

<context>
@.planning/STATE.md
@scripts/glyphos_openai_gateway.py
@integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/glyph_to_prompt.py
@.planning/phases/10-context-injection-tuning/10-context-injection-tuning-01-PLAN.md
@.planning/phases/10-context-injection-tuning/10-context-injection-tuning-02-PLAN.md
</context>

<interfaces>
From scripts/glyphos_openai_gateway.py (current context handling):
```python
# retrieve_context() returns:
{
    "context": "",           # Empty string when no results
    "used": False,
    "status": "unavailable", # "retrieved" | "unavailable" | "error"
    "search_strategy": "substring",
    "search_degraded": True,
    "search_suggestions": [...],
}
```

Current assemble_prompt_raw() behavior (lines 740-768):
- If context is empty string, returns raw_prompt unchanged
- If context has content, wraps in [Retrieved Context] block
- assemble_prompt() adds [Glyph Encoding v1] block when encoding was used

Response headers currently set (lines ~950+):
- X-LMM-Route-Target
- X-LMM-Route-Reason
- X-LMM-Encoding-Status
- X-LMM-Search-Strategy (if available)
- X-LLM-Context-Used (if available)
</interfaces>

<tasks>

<task type="auto">
  <name>Task 1: Add graceful fallback for empty and degraded context in gateway</name>
  <files>scripts/glyphos_openai_gateway.py</files>
  <action>
    In `scripts/glyphos_openai_gateway.py`, add explicit fallback handling for empty, stale, and degraded context at four levels:

    **Level 1 — Empty context (no results):**
    In `prepare_gateway_pipeline()` or the context handling section, when `context_result["status"] == "unavailable"` or `context_result["context"]` is empty/whitespace-only:
    - Skip encoding entirely (no point compressing nothing)
    - Set `pipeline["context_status"] = "empty"`
    - Do NOT include any context block in the assembled prompt
    - The GlyphPacket should carry `action="QUERY"` with low psi (from Plan 02's computation: ~0.3)
    - Set `pipeline["context_quality_score"] = 0.0`

    **Level 2 — Degraded context (substring search, low quality):**
    When `context_result["search_degraded"] == True`:
    - Allow ONLY light Ψ encoding (GE1-LINES for repeated-text compression) — never GE1-JSON, since JSON compression is brittle on degraded/fuzzy search results
    - Set `pipeline["context_status"] = "degraded"`
    - Use the encoding result: if GE1-LINES compression is effective, include encoded block; otherwise use raw context
    - The quality score (from Plan 01) will be low (< 0.3), which Plan 02 uses to avoid auto-local routing
    - Set appropriate context_quality_score (computed by Plan 01's scorer)

    **Level 3 — Stale context (good results but old index):**
    When `quality.is_stale == True` (from Plan 01's scorer, index age > 24h):
    - Set `pipeline["context_status"] = "stale"`
    - Allow full Ψ encoding (both GE1-JSON and GE1-LINES) — content is still valid, just potentially outdated
    - Log a note that stale context was used (for operator awareness)
    - Quality score is NOT penalized for staleness (it's still good content), but the `is_stale` flag enables downstream decisions (e.g., background re-index trigger)

    **Level 4 — Error context (MCP bridge failure):**
    When `context_result["status"] == "error"`:
    - Treat same as empty context — no context, no encoding
    - Set `pipeline["context_status"] = "error"`
    - Log a warning but do NOT fail the request (context is optional)

    **Response headers** — add `X-LMM-Context-Status` header with values: "available", "empty", "degraded", "stale", "error". This is in addition to existing headers.

    The `assemble_prompt_raw()` function already handles empty context correctly (returns raw_prompt unchanged), so no changes needed there. The main changes are:
    1. Explicit status classification in the pipeline
    2. Skipping encoding for empty/degraded cases
    3. New response header
  </action>
  <verify>
    <automated>bash -c 'cd /opt/llama-model-manager-v2.1.0 && python3 -c "
import ast, sys
with open("scripts/glyphos_openai_gateway.py") as f:
    source = f.read()

# Verify context_status handling exists
checks = [
    "context_status",
    "context.*empty|context.*degraded|context.*error",
]
import re
for pattern in checks:
    if re.search(pattern, source):
        print(f"Found: {pattern}")
    else:
        print(f"MISSING: {pattern}", file=sys.stderr)
        sys.exit(1)
print("context fallback patterns found")
"'</automated>
  </verify>
  <done>
    Gateway explicitly classifies context as "available", "empty", "degraded", or "error". Encoding is skipped for empty and degraded context. X-LMM-Context-Status response header is set. Requests proceed normally even when context is missing (context is optional).
  </done>
</task>

<task type="auto">
  <name>Task 2: Update prompt assembly for clean context block handling</name>
  <files>integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/glyph_to_prompt.py</files>
  <action>
    In `glyph_to_prompt.py`, ensure the `build_prompt_from_packet()` function (or equivalent prompt assembly) handles all context states cleanly.

    Check if `build_prompt_from_packet()` already exists (from Phase 09). If it does NOT exist yet (Phase 09 not shipped), add a minimal version:

    ```python
    def build_prompt_from_packet(
        glyph_packet: GlyphPacket,
        context: Optional[str] = None,
        context_status: str = "available",  # "available" | "empty" | "degraded" | "stale" | "error"
        encoding_status: str = "none",
        user_message: str = "",
    ) -> str:
        """Build prompt from GlyphPacket with context-aware assembly.

        Context status handling:
        - "available" / "stale": Include context block (encoded or raw based on encoding_status)
        - "empty" / "error": No context block, just packet + user message
        - "degraded": Raw context by default; GE1-LINES allowed if encoding effective
        """
    ```

    Degraded context encoding policy:
    - GE1-LINES (repeated-line compression) is safe on degraded content — it's purely structural
    - GE1-JSON (key aliasing) should be skipped for degraded context — fuzzy matches produce noisy JSON that compresses poorly or loses semantics
    - The gateway should check `encoding_format` and skip GE1-JSON when status is "degraded"

    Helper functions:
    ```python
    def _build_raw_context_block(context: str) -> str:
        return "\n".join([
            "[Retrieved Context]",
            context,
        ])

    def _build_encoded_context_block(encoded_context: str, packet: GlyphPacket) -> str:
        return "\n".join([
            "[Glyph Encoding v1]",
            "Decode this compact context before reasoning.",
            f"Format: {packet.encoding_format}",
            encoded_context,
        ])
    ```

    If Phase 09 has already shipped and `build_prompt_from_packet()` exists, ADD the `context_status` parameter and update the logic to handle empty/degraded/available states.

    Also ensure the gateway's `assemble_prompt_raw()` and `assemble_prompt()` functions use context_status to decide whether to include encoding.
  </action>
  <verify>
    <automated>python3 -c "
# Verify prompt assembly handles all context statuses
from pathlib import Path

# Check if the file exists and has the expected patterns
p = Path('integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/glyph_to_prompt.py')
if p.exists():
    content = p.read_text()
    # Must handle at least these context states
    for status in ['available', 'empty', 'degraded']:
        if status in content.lower() or 'context_status' in content:
            print(f'Found handling for: {status}')
        else:
            print(f'Need to add handling for: {status}')
    print('glyph_to_prompt.py reviewed')
else:
    print('File does not exist yet - will be created by this plan')
"</automated>
  </verify>
  <done>
    build_prompt_from_packet() (or existing equivalent) handles all 4 context statuses: available, empty, degraded, error. Encoded context is only used when status is "available" AND encoding_status is "encoded". Empty/error context produces no context block. Degraded context uses raw block only.
  </done>
</task>

</tasks>

<verification>
- Gateway classifies context into one of 5 statuses: available, empty, degraded, stale, error
- Empty context → no context block, no encoding, psi ~0.3
- Degraded context → GE1-LINES allowed (safe structural compression), GE1-JSON skipped, low quality score
- Stale context → full Ψ encoding allowed, quality score not penalized, is_stale flag set
- Error context → treated same as empty, request proceeds
- X-LMM-Context-Status header is set on all responses
- Prompt assembly correctly includes/excludes context blocks based on status
- Ψ encoding is NEVER applied to empty or error context
- Ψ GE1-JSON is NEVER applied to degraded context (GE1-LINES allowed)
</verification>

<success_criteria>
- Context status is explicitly tracked through the pipeline ("available", "empty", "degraded", "stale", "error")
- Empty context: no context block, no encoding, psi ~0.3
- Degraded context: GE1-LINES allowed (safe structural compression), GE1-JSON skipped, quality score reflects degradation
- Stale context: full Ψ encoding allowed, quality score not penalized, is_stale flag set, operator note logged
- Error context: same as empty, warning logged, request proceeds
- X-LMM-Context-Status response header reflects the actual context state
- No silent failures or edge-case behavior when context is missing or poor
- All 5 context statuses produce correct prompt assembly
</success_criteria>

<output>
After completion, create `.planning/phases/10-context-injection-tuning/10-context-injection-tuning-03-SUMMARY.md`
</output>
