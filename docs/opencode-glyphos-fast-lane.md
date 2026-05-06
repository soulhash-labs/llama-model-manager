# OpenCode GlyphOS Fast Lane

## Endpoint Map

- Full GlyphOS lane: `http://127.0.0.1:4010/v1`
- Fast GlyphOS lane: `http://127.0.0.1:4011/v1`
- Raw llama.cpp backend: `http://127.0.0.1:8081/v1`

Use the full lane for normal harness traffic. Use the fast lane for latency-sensitive OpenCode or agent traffic that still needs the LMM/GlyphOS boundary but cannot wait on long context preflight work. Treat raw `8081` as backend/internal unless you intentionally choose direct diagnostic mode.

## Operation

Start the full gateway:

```bash
llama-model gateway start
```

Start the fast gateway:

```bash
llama-model gateway fast start
```

Check status:

```bash
llama-model gateway status
llama-model gateway fast status
```

The fast lane keeps protocol normalization, explicit upstream context, GlyphOS prompt shaping, route metadata, and response normalization. Its difference is the context preflight budget: optional MCP retrieval is sharply bounded and indexing is skipped.

## OpenCode Sync

`llama-model sync-opencode` writes:

- `llamacpp` provider for the selected route mode
- `glyphos` provider for the full lane
- `glyphos-fast` provider for the fast lane

The selected OpenCode model remains local-first. The extra GlyphOS provider entries make fast/full routing explicit for operator or harness selection without making raw llama.cpp the default fallback.

## Manual Cloud Override

Cloud is an operator choice. Local llama.cpp remains the default when available.

Use cloud only when a request or operator config explicitly asks for it, for example through a context routing hint:

```json
{
  "routing_hints": {
    "preferred_backend": "openai"
  }
}
```

Remove that hint or restore `preferred_backend` to `llamacpp` to return to local-first routing.

## Dashboard Diagnostics

The dashboard shows:

- full and fast gateway endpoints
- backend endpoint
- effective token/timeout/SSE policy
- recent route target
- recent context status
- context degradation and encoding status

Use the Gateway Trace panel to diagnose slow first-token behavior. If context is degraded or deferred, check the fast-lane context budgets and the Context MCP status before changing model or backend settings.
