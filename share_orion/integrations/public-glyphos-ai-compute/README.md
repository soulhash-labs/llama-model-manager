# public-glyphos-ai-compute

Clean public package for the GlyphOS glyph layer and AI routing layer.

This repo intentionally includes only:

- glyph encoding and packet types
- psi/coherence pulse primitives
- prompt shaping
- AI routing
- local/external provider clients

This repo intentionally excludes the private Q45 / quantum stack.

## Public Layers

### 1. Glyph layer
- `glyphos_ai/glyph/types.py`
- `glyphos_ai/glyph/encoder.py`
- `glyphos_ai/glyph/pulse.py`

### 2. AI routing layer
- `glyphos_ai/ai_compute/router.py`
- `glyphos_ai/ai_compute/api_client.py`
- `glyphos_ai/ai_compute/glyph_to_prompt.py`

## Installation

```bash
pip install -e .
```

## Quick Start

```python
from glyphos_ai import create_packet, decode_packet, glyph_to_prompt, AdaptiveRouter

packet = create_packet("QUERY", "MODEL", psi=0.85, time_slot=7)
decoded = decode_packet(packet)
prompt = glyph_to_prompt(decoded)
router = AdaptiveRouter()
result = router.route(decoded, prompt=prompt)
print(result.target.value, result.routing_reason)
```

## Local llama.cpp Support

The public package supports direct routing to a local OpenAI-compatible `llama.cpp` endpoint.

Default local endpoint:
- `http://127.0.0.1:8081/v1`

Environment variables:
- `GLYPHOS_LLAMACPP_URL`
- `GLYPHOS_LLAMACPP_MODEL`
- `GLYPHOS_LLAMACPP_TIMEOUT`
- lane-specific overrides such as:
  - `GLYPHOS_LLAMACPP_TERRAN_URL`
  - `GLYPHOS_LLAMACPP_AURORA_URL`
  - `GLYPHOS_LLAMACPP_STARLIGHT_URL`
  - `GLYPHOS_LLAMACPP_POLARIS_URL`

## Config

Sample config lives at:
- `config/default.yaml`

If `PyYAML` is installed, the runtime can also read `~/.glyphos/config.yaml`.
If not, environment variables remain the canonical configuration path.

## Notes

- Q45 / quantum integration is private and intentionally split into a separate internal repo.
- This package is intended to integrate cleanly with an external runtime owner such as `llama-model-manager`.

## Trademark Notice

- `Soul Hash®` is a registered trademark of soulhash.ai
- `GlyphOS™` is a trademark of soulhash.ai
- This bundled public package does not grant trademark rights beyond the applicable license and notice terms
