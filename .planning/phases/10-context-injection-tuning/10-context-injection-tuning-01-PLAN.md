---
phase: 10-context-injection-tuning
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - integrations/public-glyphos-ai-compute/glyphos_ai/glyph/context_quality.py
  - integrations/public-glyphos-ai-compute/glyphos_ai/glyph/__init__.py
  - integrations/public-glyphos-ai-compute/glyphos_ai/glyph/types.py
  - scripts/glyphos_openai_gateway.py
autonomous: true
requirements:
  - CONTEXT-01
  - CONTEXT-02

must_haves:
  truths:
    - "Gateway can compute a context quality score from search results"
    - "Score is a float 0.0-1.0 reflecting result count, degradation, strategy, and recency"
    - "Score is attached to context pipeline metadata"
    - "is_stale flag is set when index is older than 24h"
  artifacts:
    - path: "integrations/public-glyphos-ai-compute/glyphos_ai/glyph/context_quality.py"
      provides: "Context quality scoring implementation"
      exports: ["compute_context_quality_score", "ContextQualityScore"]
    - path: "scripts/glyphos_openai_gateway.py"
      provides: "Gateway populates quality score from search results"
      pattern: "compute_context_quality_score|context_quality_score"
  key_links:
    - from: "scripts/glyphos_openai_gateway.py"
      to: "glyphos_ai/glyph/context_quality.py"
      via: "import + call in retrieve_context or prepare_gateway_pipeline"
      pattern: "compute_context_quality_score"
---

<objective>
Add context quality scoring so the gateway can quantify how good retrieved context is. Currently context quality is only a boolean `degraded` flag — this adds a 0.0-1.0 score that downstream plans (Plan 02) will use to auto-boost psi and make routing decisions.

Purpose: Replace the opaque boolean degraded flag with a continuous quality metric.
Output: `ContextQualityScore` dataclass, scoring function, gateway integration.
</objective>

<execution_context>
@/home/angelo/.config/opencode/get-shit-done/workflows/execute-plan.md
@/home/angelo/.config/opencode/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/ROADMAP.md
@.planning/STATE.md
@scripts/glyphos_openai_gateway.py
@integrations/public-glyphos-ai-compute/glyphos_ai/glyph/types.py
@integrations/context-mode-mcp/src/db/search.ts
</context>

<interfaces>
<!-- Key types from the codebase that Plan 01 will extend/reference. -->

From integrations/public-glyphos-ai-compute/glyphos_ai/glyph/types.py:
```python
@dataclass
class GlyphPacket:
    instance_id: str
    psi_coherence: float
    action: str
    header: str = "H"
    time_slot: str = "T00"
    destination: str = ""
```

From scripts/glyphos_openai_gateway.py (retrieve_context return shape):
```python
{
    "context": str,            # Retrieved context text
    "used": bool,              # Whether context was used
    "status": str,             # "retrieved" | "unavailable" | "error"
    "search_strategy": str,    # "rrf" | "fts_porter" | "fts_trigram" | "substring"
    "search_degraded": bool,   # True when FTS5 unavailable
    "search_suggestions": list[str],  # Typo suggestions when degraded
    "chunks": list[dict],      # [{score, rank, snippet, ...}]
}
```

From integrations/context-mode-mcp/src/db/search.ts (chunk shape):
```typescript
{
    rank: number,        // 0-based rank
    chunk_id: string,
    title: string,
    snippet: string,
    score: number,       // BM25 + proximity boost
    uri: string,
}
```

Strategy quality hierarchy (best → worst):
1. "rrf" — Reciprocal Rank Fusion of both FTS5 tables (best)
2. "fts_porter" — FTS5 porter tokenizer (good)
3. "fts_trigram" — FTS5 trigram tokenizer (okay)
4. "substring" — LIKE fallback, sets degraded=true (worst)
</interfaces>

<tasks>

<task type="auto">
  <name>Task 1: Create ContextQualityScore dataclass and scoring function</name>
  <files>integrations/public-glyphos-ai-compute/glyphos_ai/glyph/context_quality.py</files>
  <action>
    Create a new file `context_quality.py` in the glyphos_ai glyph package.

    1. **Define `ContextQualityScore` dataclass** with these fields:
    ```python
    @dataclass
    class ContextQualityScore:
        score: float              # 0.0 (no context) to 1.0 (excellent)
        result_count: int         # Number of chunks returned
        is_degraded: bool         # Whether FTS5 was unavailable
        is_stale: bool            # True if index age > 24h (good results but old)
        strategy: str             # Search strategy used
        top_score: float          # Highest chunk score (BM25 + proximity)
        avg_score: float          # Mean chunk score (0.0 if no results)
    ```

    Add `is_stale` — set to `True` when the context result includes an `index_age_hours` field > 24, or when the gateway can infer staleness from `last_indexed` metadata. Default `False` when unknown.

    2. **Implement `compute_context_quality_score()` function** that takes the context result dict (same shape that `retrieve_context()` returns) and computes a quality score:

    ```python
    def compute_context_quality_score(context_result: dict[str, Any]) -> ContextQualityScore:
    ```

    Scoring algorithm (std-lib only, no external deps):
    - **Base score from result_count**: log-scaled contribution
      - 0 results → 0.0
      - 1-3 results → 0.2-0.4
      - 4-8 results → 0.5-0.7
      - 9+ results → 0.8-0.9
    - **Strategy multiplier**:
      - "rrf" → 1.0x (no penalty)
      - "fts_porter" → 0.95x
      - "fts_trigram" → 0.85x
      - "substring" → 0.5x (degraded search)
    - **Degradation penalty**: If `search_degraded=True`, multiply by 0.4
    - **Top score bonus**: If top chunk score > 2.0, add up to 0.1 bonus
    - **Recency bonus**: If `index_age_hours` is available and < 24h, add up to 0.05 bonus. Linear decay: 0.05 at 0h → 0.0 at 24h. If > 24h, set `is_stale=True` (no penalty, but flag is set). If unknown, no bonus and `is_stale=False`.
    - **Clamp final score to 0.0-1.0**

    Example: 5 results, rrf strategy, not degraded, top score 3.2:
    - Base from count: ~0.6
    - Strategy: 0.6 * 1.0 = 0.6
    - Not degraded: 0.6 * 1.0 = 0.6
    - Top score bonus: 0.6 + 0.1 = 0.7
    - Final: min(0.7, 1.0) = 0.7

    The function must be robust to missing keys, empty chunks list, and None values — return a zero-score result for invalid input.

    3. **Add unit-style inline tests** as a `if __name__ == "__main__"` block:
    - Empty context → score 0.0
    - Single result, substring, degraded → low score (~0.08)
    - Many results, rrf, not degraded → high score (~0.7-0.9)
  </action>
  <verify>
    <automated>python3 integrations/public-glyphos-ai-compute/glyphos_ai/glyph/context_quality.py && echo "inline tests passed"</automated>
  </verify>
  <done>
    ContextQualityScore dataclass exists with score/result_count/is_degraded/strategy/top_score/avg_score fields. compute_context_quality_score() produces 0.0 for empty results and 0.7+ for good rrf results.
  </done>
</task>

<task type="auto">
  <name>Task 2: Export scoring function and wire into gateway pipeline</name>
  <files>
    integrations/public-glyphos-ai-compute/glyphos_ai/glyph/__init__.py,
    integrations/public-glyphos-ai-compute/glyphos_ai/glyph/types.py,
    scripts/glyphos_openai_gateway.py
  </files>
  <action>
    1. **Export from glyph package** — Add `from glyphos_ai.glyph.context_quality import compute_context_quality_score, ContextQualityScore` to `__init__.py`.

    2. **Add context_quality_score to ContextPayload** (in types.py, or if ContextPayload doesn't exist yet from Phase 09, add it to GlyphPacket or create a minimal ContextPayload):
    ```python
    # If ContextPayload already exists (from Phase 09), add:
    context_quality_score: float = 0.0

    # If NOT, add to the pipeline metadata dict returned by prepare_gateway_pipeline:
    # pipeline["context_quality_score"] = quality_score.score
    ```
    IMPORTANT: Check if Phase 09 has already been executed (look for ContextPayload dataclass in types.py). If Phase 09 has NOT shipped yet, use a dict field in the pipeline metadata instead of modifying types.py. This avoids coupling to an unshipped phase.

    3. **Wire into gateway** — In `scripts/glyphos_openai_gateway.py`, modify `prepare_gateway_pipeline()` or `retrieve_context()` to call `compute_context_quality_score(context_result)` and attach the score to the pipeline metadata:
    ```python
    from glyphos_ai.glyph.context_quality import compute_context_quality_score

    # After retrieve_context():
    quality = compute_context_quality_score(context_result)
    # Attach to pipeline:
    pipeline["context_quality_score"] = quality.score
    pipeline["context_quality"] = quality  # full object for downstream use
    ```

    4. **Add to telemetry** — In the request record/telemetry dict that gets emitted, include `"context_quality_score": quality.score` and `"context_quality_strategy": quality.strategy`.

    Do NOT change the psi_coherence value yet — that's Plan 02. Only compute and attach the score.
  </action>
  <verify>
    <automated>bash -c 'cd /opt/llama-model-manager-v2.1.0 && python3 -c "from glyphos_ai.glyph.context_quality import compute_context_quality_score, ContextQualityScore; print(\"imports ok\")"'</automated>
  </verify>
  <done>
    compute_context_quality_score is importable from glyphos_ai.glyph. Gateway pipeline metadata includes context_quality_score. Telemetry records include the score.
  </done>
</task>

</tasks>

<verification>
- `python3 integrations/public-glyphos-ai-compute/glyphos_ai/glyph/context_quality.py` runs without error (inline tests pass)
- `python3 -c "from glyphos_ai.glyph.context_quality import compute_context_quality_score"` succeeds
- Gateway telemetry records contain context_quality_score field (verify by checking the telemetry dict construction in glyphos_openai_gateway.py)
</verification>

<success_criteria>
- ContextQualityScore dataclass with all 7 fields implemented (score, result_count, is_degraded, is_stale, strategy, top_score, avg_score)
- compute_context_quality_score() returns 0.0 for empty/no results
- compute_context_quality_score() returns 0.7+ for 5+ rrf results with good chunk scores
- compute_context_quality_score() sets is_stale=True when index_age_hours > 24
- compute_context_quality_score() adds recency bonus when index_age_hours < 24
- Gateway pipeline carries context_quality_score through to telemetry
- No changes to psi_coherence yet (Phase 10 Plan 02 will add that)
- Backward compatible: works whether or not Phase 09 has shipped
</success_criteria>

<output>
After completion, create `.planning/phases/10-context-injection-tuning/10-context-injection-tuning-01-SUMMARY.md`
</output>
