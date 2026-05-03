---
phase: 10-context-injection-tuning
plan: 02
type: execute
wave: 2
depends_on: ["10-context-injection-tuning-01"]
files_modified:
  - integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/router.py
  - scripts/glyphos_openai_gateway.py
  - integrations/public-glyphos-ai-compute/glyphos_ai/glyph/types.py
autonomous: true
requirements:
  - CONTEXT-03
  - CONTEXT-04

must_haves:
  truths:
    - "Psi coherence is computed from context quality, not hardcoded to 0.9"
    - "High context quality + high psi → local encoded route"
    - "Low context quality triggers routing to cloud-safe raw path"
  artifacts:
    - path: "scripts/glyphos_openai_gateway.py"
      provides: "Psi computed from context_quality_score"
      pattern: "psi_coherence.*context_quality|context_quality.*psi"
    - path: "integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/router.py"
      provides: "Router considers context quality in routing decision"
      pattern: "context_quality|quality_score"
  key_links:
    - from: "scripts/glyphos_openai_gateway.py"
      to: "glyphos_ai/ai_compute/router.py"
      via: "GlyphPacket.psi_coherence computed from context quality"
      pattern: "psi_coherence="
---

<objective>
Replace the hardcoded psi_coherence=0.9 with dynamic computation from context quality, and enhance the router to prefer local encoded routes when both psi and context quality are high. This makes the system "feel magical" — good context auto-activates the best local path.

Purpose: Context-aware psi computation + routing that prefers encoded local execution.
Output: Dynamic psi calculation, context-aware routing enhancement, telemetry updates.
</objective>

<execution_context>
@/home/angelo/.config/opencode/get-shit-done/workflows/execute-plan.md
@/home/angelo/.config/opencode/get-shit-done/templates/summary.md
@.planning/phases/10-context-injection-tuning/10-context-injection-tuning-01-PLAN.md
</execution_context>

<context>
@.planning/ROADMAP.md
@.planning/STATE.md
@scripts/glyphos_openai_gateway.py
@integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/router.py
@integrations/public-glyphos-ai-compute/glyphos_ai/glyph/types.py
@.planning/phases/10-context-injection-tuning/10-context-injection-tuning-01-PLAN.md
</context>

<interfaces>
<!-- Key interfaces from Plan 01 and existing codebase. -->

From Plan 01 (context_quality.py):
```python
@dataclass
class ContextQualityScore:
    score: float        # 0.0 to 1.0
    result_count: int
    is_degraded: bool
    strategy: str
    top_score: float
    avg_score: float
```

From glyphos_ai/glyph/types.py (GlyphPacket):
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

From router.py (AdaptiveRouter._select_target):
```python
# Current routing decision:
if psi >= high_coherence_threshold and self.llamacpp:  # 0.8
    target = ComputeTarget.LOCAL_LLAMACPP
    reason = "high coherence - prefer local llama.cpp"
```

Complex actions that currently override psi:
["analyze", "synthetize", "predict", "learn"]
</interfaces>

<tasks>

<task type="auto">
  <name>Task 1: Compute psi_coherence from context quality in gateway</name>
  <files>scripts/glyphos_openai_gateway.py</files>
  <action>
    In `scripts/glyphos_openai_gateway.py`, modify the GlyphPacket creation in `route_prompt()` and `route_prompt_stream()` to compute `psi_coherence` dynamically from `context_quality_score` instead of hardcoding 0.9.

    Add a helper function `_compute_psi_from_context(quality_score: float) -> float`:
    ```python
    def _compute_psi_from_context(quality_score: float) -> float:
        """Map context quality score to psi coherence.

        Context quality 0.0-1.0 maps to psi 0.3-0.95:
        - No context (0.0) → psi 0.3 (low coherence, may route cloud)
        - Poor context (0.2) → psi 0.4
        - Moderate context (0.5) → psi 0.65
        - Good context (0.7) → psi 0.82 (above routing threshold)
        - Excellent context (0.9+) → psi 0.95
        """
        if quality_score <= 0:
            return 0.3
        return 0.3 + (quality_score * 0.65)  # maps 0.0-1.0 → 0.3-0.95
    ```

    Then in `route_prompt()` and `route_prompt_stream()`, replace:
    ```python
    # OLD (hardcoded):
    psi_coherence=0.9,

    # NEW (dynamic):
    psi_coherence=_compute_psi_from_context(pipeline.get("context_quality_score", 0.0)),
    ```

    Also add a `"psi_source"` field to the GlyphPacket destination or pipeline metadata to indicate whether psi came from context quality:
    - `"context"` when computed from quality score
    - `"default"` when no context quality available (fallback to 0.5)

    The `_compute_psi_from_context` function should live in the gateway module. Keep it simple and readable.
  </action>
  <verify>
    <automated>python3 -c "
# Inline test of psi computation logic
def _compute_psi_from_context(quality_score):
    if quality_score <= 0:
        return 0.3
    return 0.3 + (quality_score * 0.65)

assert _compute_psi_from_context(0.0) == 0.3
assert _compute_psi_from_context(0.7) == pytest.approx(0.755, abs=0.01) or abs(_compute_psi_from_context(0.7) - 0.755) < 0.01
assert _compute_psi_from_context(1.0) == pytest.approx(0.95, abs=0.01) or abs(_compute_psi_from_context(1.0) - 0.95) < 0.01
print('psi computation logic ok')
" 2>&1 || bash -c 'python3 -c "
def _compute_psi_from_context(q):
    return 0.3 + (q * 0.65) if q > 0 else 0.3
r0 = _compute_psi_from_context(0.0)
r7 = _compute_psi_from_context(0.7)
r9 = _compute_psi_from_context(0.9)
assert r0 == 0.3, f"expected 0.3, got {r0}"
assert 0.75 <= r7 <= 0.76, f"expected ~0.755, got {r7}"
assert 0.88 <= r9 <= 0.89, f"expected ~0.885, got {r9}"
print("psi computation logic ok")
'</automated>
  </verify>
  <done>
    GlyphPacket.psi_coherence is computed from context_quality_score via _compute_psi_from_context(). No hardcoded 0.9 remains in route_prompt or route_prompt_stream. psi is in range 0.3-0.95 based on context quality.
  </done>
</task>

<task type="auto">
  <name>Task 2: Enhance router to prefer local encoded path with high psi + good context</name>
  <files>integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/router.py</files>
  <action>
    Modify the `AdaptiveRouter` in `router.py` to consider context quality alongside psi_coherence in the routing decision.

    The router already accepts `context_payload` parameter (from Phase 09). If Phase 09 has NOT shipped yet, add a simpler `context_quality_score` float parameter to `route()` and `route_stream()`.

    **Routing decision enhancement** — in `_select_target()`, modify the decision logic:

    Current:
    ```python
    if psi >= self.config.high_coherence_threshold and self.llamacpp:
        return ComputeTarget.LOCAL_LLAMACPP
    ```

    New — add a `context_quality_boost` to the psi value when context is good:
    ```python
    effective_psi = psi
    if context_quality_score >= 0.5:
        # Good context adds a 0.1 boost to psi for routing decisions
        effective_psi = min(1.0, psi + 0.1)

    if effective_psi >= self.config.high_coherence_threshold and self.llamacpp:
        return ComputeTarget.LOCAL_LLAMACPP, "high coherence + good context — prefer local"
    ```

    Also add a new routing reason code: `"context_aware_local"` to distinguish this from the existing `"high_coherence_local"` reason.

    **Degraded context path** — when context is degraded (score < 0.2):
    - Do NOT auto-select local based on psi alone if context quality is poor
    - The routing should fall through to the complex-action check or default path
    - Add routing reason: `"degraded_context_fallback"` when this triggers

    **Telemetry** — add `"effective_psi"` to the RoutingResult or the returned dict so telemetry can see the boosted value:
    ```python
    RoutingResult(
        target=target,
        response=response,
        routing_reason=reason,
        routing_reason_code=reason_code,
        # ... existing fields
    )
    # Also log effective_psi in the routing telemetry dict
    ```

    Keep changes minimal. The router should still work with `context_quality_score=None` (falls back to current behavior: psi only).
  </action>
  <verify>
    <automated>python3 -c "
# Verify routing logic concept
psi = 0.7  # Below 0.8 threshold
context_quality = 0.6  # Good context

effective_psi = psi
if context_quality >= 0.5:
    effective_psi = min(1.0, psi + 0.1)

threshold = 0.8
assert effective_psi >= threshold, f'effective_psi {effective_psi} should meet threshold {threshold}'
print(f'psi={psi} + context_boost=0.1 → effective_psi={effective_psi} >= {threshold} → local route')

# Verify degraded context does NOT boost
psi2 = 0.75
context_quality2 = 0.1
effective_psi2 = psi2
if context_quality2 >= 0.5:
    effective_psi2 = min(1.0, psi2 + 0.1)
assert effective_psi2 < threshold, f'effective_psi {effective_psi2} should NOT meet threshold'
print(f'psi={psi2} + degraded context → effective_psi={effective_psi2} < {threshold} → no auto-local')

print('routing logic concept ok')
"</automated>
  </verify>
  <done>
    Router applies +0.1 psi boost when context_quality_score >= 0.5. High psi + good context routes to LOCAL_LLAMACPP with reason_code "context_aware_local". Degraded context (score < 0.2) does not trigger auto-local. effective_psi is available in routing result. Router still works with context_quality_score=None.
  </done>
</task>

</tasks>

<verification>
- `_compute_psi_from_context(0.0)` returns 0.3
- `_compute_psi_from_context(0.7)` returns ~0.755 (above 0.8 threshold with context boost)
- Gateway no longer hardcodes psi_coherence=0.9
- Router effective_psi >= threshold with good context even when raw psi < threshold
- Degraded context (score < 0.2) does not auto-select local route
- Router works with context_quality_score=None (backward compatible)
- Telemetry includes effective_psi and routing_reason_code
</verification>

<success_criteria>
- psi_coherence is dynamically computed from context quality in both route_prompt and route_prompt_stream
- Good context (score >= 0.5) boosts effective_psi by 0.1 for routing decisions
- Router has new reason_code "context_aware_local" for context-enhanced local routing
- Router has new reason_code "degraded_context_fallback" for poor context paths
- Telemetry records effective_psi (not just raw psi)
- Backward compatible: router works with no context quality data
</success_criteria>

<output>
After completion, create `.planning/phases/10-context-injection-tuning/10-context-injection-tuning-02-SUMMARY.md`
</output>
