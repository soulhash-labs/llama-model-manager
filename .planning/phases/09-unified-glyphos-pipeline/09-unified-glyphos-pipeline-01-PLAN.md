# Plan 09: Unified GlyphOS Pipeline

## Problem Statement

The GlyphOS pipeline has a **critical architectural flaw**: context encoding and routing are decoupled when they must be unified. This creates a silent data corruption bug when requests fall back to cloud backends.

### Current Architecture (Broken)

```
glyphos_openai_gateway.py (preprocessing layer)
  ├── retrieve_context()        → gets project context from MCP
  ├── glyph_encode_context()    → Ψ compresses it (GE1-JSON / GE1-LINES)
  └── assemble_prompt()         → wraps in [Glyph Encoding v1]
        ↓
route_prompt() → GlyphPacket → AdaptiveRouter
  ├── Router sees NO encoding metadata
  ├── Routing decision based ONLY on psi_coherence + action
  ├── If local llama.cpp → fine (model might understand Ψ)
  ├── If cloud fallback → CORRUPTION (OpenAI/Claude/XAI can't decode Ψ)
  └── Packet looks identical whether encoded or raw
```

### What Breaks in Practice

| Scenario | What Happens | Result |
|----------|-------------|--------|
| Local llama.cpp available | Router sends to `:8081` | Ψ encoding works (model trained on it) |
| Local down, cloud fallback | Router sends to OpenAI/Claude | **Model receives `[Glyph Encoding v1]\nGE1-JSON {...}` — garbage** |
| High-coherence + complex action | Router sends to Anthropic | **Same corruption — no encoding awareness** |
| Gateway telemetry | Records `glyph_encoding_used: true` | **No way to correlate with route target** |

### Root Causes

1. **The router is blind** — `AdaptiveRouter` has no concept of encoding. It routes based on `psi_coherence` and `action` alone. An encoded prompt looks identical to a raw one.

2. **Encoding happens outside the routing layer** — `glyph_encode_context()` is a preprocessing step in the gateway, completely decoupled from the `glyphos_ai` package. The router and encoder don't communicate.

3. **GlyphPacket metadata is incomplete** — `GlyphPacket` carries `instance_id`, `psi_coherence`, `action`, `header`, `time_slot`, `destination` — but no `encoding_status`, `encoding_format`, or `raw_context_chars`.

4. **Cloud backends can't decode Ψ** — The GE1 encoding format (`GE1-JSON`, `GE1-LINES`) is a soulhash.ai-specific convention. OpenAI, Claude, and xAI have never seen it. When routed to cloud, the "compression" becomes corruption.

## Solution: Unified GlyphOS Pipeline

Encoding must be a **routing decision**, not a preprocessing step. The router decides whether to encode based on the target backend.

### New Architecture

```
glyphos_openai_gateway.py (orchestration layer)
  ├── retrieve_context()        → gets project context from MCP
  ├── assemble_prompt()         → wraps context (raw, no encoding yet)
  └── route_prompt() → GlyphPacket (with encoding metadata)
        ↓
AdaptiveRouter
  ├── IF target == llamacpp    → apply Ψ encoding BEFORE sending
  ├── IF target == cloud       → send raw context (skip encoding)
  ├── IF target == fallback    → send raw context (skip encoding)
  └── Records encoding decision in telemetry
```

### Key Design Principle

**The router owns the encoding decision.** The gateway assembles the prompt with raw context. The router applies Ψ encoding only when the target backend can decode it (local llama.cpp).

## Implementation Tasks

### Task 1: Extend GlyphPacket with Encoding Metadata

**Files:** `integrations/public-glyphos-ai-compute/glyphos_ai/glyph/types.py`

Add three fields to `GlyphPacket`:

```python
@dataclass
class GlyphPacket:
    instance_id: str
    psi_coherence: float
    action: str
    header: str = "H"
    time_slot: str = "T00"
    destination: str = ""
    # NEW: encoding metadata
    encoding_status: str = "none"       # "none" | "encoded" | "skipped"
    encoding_format: str = ""           # "GE1-JSON" | "GE1-LINES" | ""
    encoding_ratio: float = 1.0         # encoded_chars / raw_chars (lower = better)
```

Also add a `ContextPayload` dataclass to carry context state through the pipeline:

```python
@dataclass
class ContextPayload:
    raw_context: str                    # Always present
    raw_context_chars: int
    encoding_status: str = "none"       # "none" | "encoded" | "skipped"
    encoded_context: str = ""           # Only set if status == "encoded"
    encoding_format: str = ""           # "GE1-JSON" | "GE1-LINES"
    encoding_ratio: float = 1.0
```

### Task 2: Move Encoding Logic into glyphos_ai Package

**Files:**
- Create: `integrations/public-glyphos-ai-compute/glyphos_ai/glyph/context_encoding.py`
- Modify: `integrations/public-glyphos-ai-compute/glyphos_ai/glyph/__init__.py`
- Modify: `scripts/glyphos_openai_gateway.py`

Extract `glyph_encode_context()` from the gateway into the glyphos_ai package:

```python
# glyphos_ai/glyph/context_encoding.py
def encode_context(raw: str) -> ContextPayload:
    """Attempt to compress context using Ψ encoding.

    Returns ContextPayload with:
    - raw_context always preserved
    - encoded_context only if compression is effective
    - encoding_status indicating result
    """
    # Move logic from glyph_encode_context() here:
    # 1. Try GE1-JSON if valid JSON
    # 2. Try GE1-LINES if repeated lines
    # 3. If encoded < raw → status="encoded"
    # 4. Otherwise → status="skipped"
```

Update the gateway to use this instead of its own `glyph_encode_context()`:

```python
# glyphos_openai_gateway.py
from glyphos_ai.glyph.context_encoding import encode_context

# In prepare_gateway_pipeline():
context_result = retrieve_context(...)
context_payload = encode_context(context_result.get("context", ""))
# context_payload goes into GlyphPacket, NOT the assembled prompt yet
```

### Task 3: Router Applies Encoding Based on Target

**Files:** `integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/router.py`

Modify `AdaptiveRouter.route()` and `route_stream()`:

```python
def route(self, glyph_packet, prompt=None, context_payload=None, **kwargs):
    # context_payload carries raw + encoded context

    # Determine target first
    target = self._select_target(glyph_packet)

    # Apply encoding ONLY for local llama.cpp
    if target == ComputeTarget.LOCAL_LLAMACPP and context_payload:
        if context_payload.encoding_status == "encoded":
            # Build prompt with Ψ-encoded context
            prompt = self._build_encoded_prompt(prompt, context_payload)
        # else: use raw prompt (no encoding available)
    elif target != ComputeTarget.LOCAL_LLAMACPP and context_payload:
        # Cloud fallback — ensure NO encoding in prompt
        prompt = self._build_raw_prompt(prompt, context_payload)

    # Update packet with encoding decision
    glyph_packet.encoding_status = context_payload.encoding_status if context_payload else "none"
    glyph_packet.encoding_format = context_payload.encoding_format if context_payload else ""
    glyph_packet.encoding_ratio = context_payload.encoding_ratio if context_payload else 1.0

    # Route with full encoding awareness
    return self._execute_route(target, prompt, glyph_packet, **kwargs)
```

Add `_build_encoded_prompt()` and `_build_raw_prompt()` methods that assemble the context appropriately for each target.

### Task 4: Update glyph_to_prompt to Handle Encoding

**Files:** `integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/glyph_to_prompt.py`

Add encoding-aware prompt assembly:

```python
def build_prompt_from_packet(glyph_packet: GlyphPacket,
                              context: Optional[ContextPayload] = None,
                              user_message: str = "") -> str:
    """Build complete prompt from packet + context.

    If packet.encoding_status == "encoded" and context is present:
    → Include Ψ encoding instructions
    If packet.encoding_status == "none" or context is raw:
    → Include raw context block
    """
    base = glyph_to_prompt(glyph_packet)

    if context and context.encoding_status == "encoded":
        context_block = "\n".join([
            "[Glyph Encoding v1]",
            "Decode this compact context before reasoning.",
            f"Format: {context.encoding_format}",
            context.encoded_context,
        ])
    elif context and context.raw_context:
        context_block = "\n".join([
            "[Retrieved Context]",
            context.raw_context,
        ])
    else:
        context_block = ""

    return f"{context_block}\n\n{base}\n\nUser: {user_message}" if context_block else f"{base}\n\nUser: {user_message}"
```

### Task 5: Update Gateway Pipeline

**Files:** `scripts/glyphos_openai_gateway.py`

Refactor `prepare_gateway_pipeline()` and `route_prompt()`:

```python
def prepare_gateway_pipeline(payload, raw_prompt, *, model, stream):
    # Step 1: Retrieve context (unchanged)
    context_result = retrieve_context(payload, raw_prompt, model=model, stream=stream)

    # Step 2: Encode context (now in glyphos_ai package)
    context_payload = encode_context(context_result.get("context", ""))

    # Step 3: Build raw assembled prompt (NO encoding applied yet)
    assembled = assemble_prompt_raw(raw_prompt, context_payload)

    # Step 4: Pipeline metadata includes encoding state
    pipeline = {
        "mode": "routed-full" if context_result.get("used") else "routed-basic",
        "context_payload": context_payload,  # ← carries encoding state to router
        "context_status": context_result.get("status"),
        "context_used": context_result.get("used"),
        # ... rest of pipeline metadata
    }

    return assembled, pipeline
```

Update `route_prompt()` to pass `context_payload` through:

```python
def route_prompt(prompt, model, max_tokens, temperature, context_payload=None):
    packet = GlyphPacket(
        instance_id="lmm-gateway",
        psi_coherence=0.9,
        action="QUERY",
        header="H",
        time_slot="T00",
        destination=model or "local-llama",
        encoding_status=context_payload.encoding_status if context_payload else "none",
        encoding_format=context_payload.encoding_format if context_payload else "",
        encoding_ratio=context_payload.encoding_ratio if context_payload else 1.0,
    )
    router = create_router()
    result = router.route(packet, prompt=prompt,
                          context_payload=context_payload,  # ← router sees encoding state
                          model=model, max_tokens=max_tokens, temperature=temperature)
    # ...
```

### Task 6: Telemetry Correlation

**Files:** `scripts/glyphos_openai_gateway.py`

Update the telemetry record schema to correlate encoding with routing:

```python
record.update({
    "encoding_status": pipeline.get("context_payload").encoding_status,
    "encoding_format": pipeline.get("context_payload").encoding_format,
    "encoding_ratio": pipeline.get("context_payload").encoding_ratio,
    "route_target": routed["target"],
    "encoding_aware_routing": True,  # ← confirms router knew about encoding
})
```

Update response headers:

```python
headers["X-LMM-Encoding-Status"] = context_payload.encoding_status
headers["X-LMM-Encoding-Format"] = context_payload.encoding_format
headers["X-LMM-Route-Target"] = routed["target"]
```

### Task 7: Backward Compatibility

**Files:** `scripts/glyphos_openai_gateway.py`, `integrations/public-glyphos-ai-compute/glyphos_ai/glyph/types.py`

Ensure old gateway calls without `context_payload` still work:

- `GlyphPacket` new fields have defaults (`encoding_status="none"`, etc.)
- `AdaptiveRouter.route()` accepts `context_payload=None` (falls back to old behavior: no encoding awareness)
- Gateway `glyph_encode_context()` remains as a thin wrapper around the new `encode_context()` for any direct callers

## Success Criteria

- [ ] Cloud fallback routes NEVER receive Ψ-encoded context (raw context only)
- [ ] Local llama.cpp routes receive Ψ-encoded context when compression is effective
- [ ] GlyphPacket carries `encoding_status`, `encoding_format`, `encoding_ratio`
- [ ] Router's routing decision considers encoding state (telemetry confirms)
- [ ] Telemetry records show correlation: `encoding_status` + `route_target` per request
- [ ] Response headers include `X-LMM-Encoding-Status` and `X-LMM-Route-Target`
- [ ] Existing behavior unchanged when `context_payload=None` (backward compatible)
- [ ] Gateway `glyph_encode_context()` still works as thin wrapper (no breaking changes)

## Dependencies

- `glyphos_ai` package (`integrations/public-glyphos-ai-compute/glyphos_ai/`)
- `glyphos_openai_gateway.py` gateway server
- Existing context retrieval pipeline (MCP bridge, FTS5 search)

## Files Modified

| File | Change |
|------|--------|
| `glyphos_ai/glyph/types.py` | Add `encoding_status`, `encoding_format`, `encoding_ratio` to `GlyphPacket`; new `ContextPayload` dataclass |
| `glyphos_ai/glyph/context_encoding.py` | **NEW** — extracted encoding logic from gateway |
| `glyphos_ai/glyph/__init__.py` | Export `encode_context`, `ContextPayload` |
| `glyphos_ai/ai_compute/router.py` | Router applies encoding based on target; passes context_payload through |
| `glyphos_ai/ai_compute/glyph_to_prompt.py` | New `build_prompt_from_packet()` with encoding awareness |
| `scripts/glyphos_openai_gateway.py` | Refactor pipeline to use unified encoding; pass context_payload to router |

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Encoding logic extraction breaks existing behavior | Keep `glyph_encode_context()` as thin wrapper; add tests |
| Router changes affect existing cloud routes | Default behavior when `context_payload=None` is unchanged |
| GlyphPacket schema change breaks consumers | New fields have safe defaults; dataclass not strict |
| Performance impact from additional encoding step | Encoding was already happening; just moved location |
