# LMM, OpenCode, and oh-my-openagent Runbook

This guide is for new users who want OpenCode and oh-my-openagent to use
Llama Model Manager through the GlyphOS gateway.

The default goal is:

- local-first inference
- GlyphOS behavior preserved on user-facing lanes
- fast OpenCode lane available when latency matters
- raw llama.cpp kept as backend/internal infrastructure
- cloud routing used only when explicitly requested

## Architecture

The normal flow is:

```text
Harness -> LMM/GlyphOS -> llama.cpp or cloud backend -> model -> LMM/GlyphOS -> Harness
```

For local use:

```text
OpenCode / oh-my-openagent -> LMM/GlyphOS gateway -> llama.cpp -> local GGUF model
```

LMM/GlyphOS owns:

- OpenAI-compatible and Anthropic-compatible protocol handling
- context and prompt shaping
- route metadata
- full and fast gateway lanes
- response normalization back to the harness

llama.cpp owns only model execution.

## Endpoint Map

| Endpoint | Purpose | Use |
| --- | --- | --- |
| `http://127.0.0.1:4010/v1` | Full GlyphOS gateway | Normal routed harness traffic |
| `http://127.0.0.1:4011/v1` | Fast GlyphOS gateway | Latency-sensitive OpenCode / agent traffic |
| `http://127.0.0.1:8081/v1` | Raw llama.cpp backend | Diagnostics and internal backend only |

Use `4010` or `4011` for OpenCode when you want GlyphOS behavior. Do not make
raw `8081` the default harness endpoint unless you intentionally want to bypass
GlyphOS for diagnostics.

## Quick Start

Install or update LMM:

```bash
curl -fsSL https://soulhash.ai/install_lmm.sh | sh
```

Install OpenCode:

```bash
curl -fsSL https://opencode.ai/install | bash
```

Install oh-my-openagent by following its upstream guide. The LMM integration
expects these files when sync runs:

```text
~/.config/opencode/opencode.json
~/.config/opencode/oh-my-openagent.json
```

Start or switch to a local model:

```bash
llama-model current
llama-model doctor
```

If no model is active yet, add or switch one from the dashboard or CLI before
syncing OpenCode.

## Gateway Setup

Start the full gateway:

```bash
llama-model gateway start
```

Start the fast gateway:

```bash
llama-model gateway fast start
```

Check both:

```bash
llama-model gateway status
llama-model gateway fast status
```

Smoke-test the model surfaces:

```bash
curl -s http://127.0.0.1:4010/v1/models
curl -s http://127.0.0.1:4011/v1/models
curl -s http://127.0.0.1:8081/v1/models
```

## Sync OpenCode

Run:

```bash
llama-model sync-opencode
```

This writes OpenCode provider entries for:

- `llamacpp/<model>` for direct diagnostics
- `glyphos/<model>` for the full `4010` lane
- `glyphos-fast/<model>` for the fast `4011` lane

When the OpenCode CLI is available, sync also reads the live OpenCode model
catalog and validates the selected local model before writing config.

Expected output includes:

```text
status: synced
route_mode: routed
gateway_api_base: http://127.0.0.1:4010/v1
gateway_fast_api_base: http://127.0.0.1:4011/v1
```

After sync, refresh OpenCode:

```bash
opencode models --refresh
```

## Sync oh-my-openagent

If `~/.config/opencode/oh-my-openagent.json` exists, `llama-model sync-opencode`
also updates known oh-my-openagent agents.

The desired result is:

```text
primary model:  glyphos-fast/<model>
fallback model: glyphos/<model>
```

This gives agents the fast GlyphOS lane first, while preserving the full
GlyphOS lane as fallback.

To disable this automatic agent-layer sync:

```bash
LLAMA_MODEL_SYNC_OH_MY_OPENAGENT=0 llama-model sync-opencode
```

## GlyphOS Policy Source

The canonical runtime policy file is:

```text
~/.glyphos/config.yaml
```

or the path set by:

```bash
GLYPHOS_CONFIG_FILE=/path/to/config.yaml
```

Write/update it with:

```bash
llama-model sync-glyphos
```

The dashboard shows whether this policy file exists and which path is active.

## Manual Cloud Override

Cloud is not a hidden fallback. Local llama.cpp remains the default when
available.

Use cloud only when an operator or request explicitly asks for it, for example:

```json
{
  "routing_hints": {
    "preferred_backend": "openai"
  }
}
```

Remove the hint, or set `preferred_backend` back to `llamacpp`, to return to
local-first routing.

Important distinction:

- `locality: external` means context came from outside LMM.
- It does not mean "route this request to cloud."

## Verify The Setup

Run these checks after install/sync:

```bash
command -v llama-model
command -v opencode
llama-model doctor
llama-model gateway status
llama-model gateway fast status
opencode models --refresh
```

Inspect config files:

```bash
cat ~/.config/opencode/opencode.json
cat ~/.config/opencode/oh-my-openagent.json
cat ~/.glyphos/config.yaml
```

Check for these model IDs:

```text
llamacpp/<model>
glyphos/<model>
glyphos-fast/<model>
```

For a working fast-lane setup, oh-my-openagent entries should point at
`glyphos-fast/<model>` first and `glyphos/<model>` as fallback.

## Measure Fast Lane Latency

Measure all three surfaces on the target machine:

```bash
curl -N http://127.0.0.1:4010/v1/chat/completions
curl -N http://127.0.0.1:4011/v1/chat/completions
curl -N http://127.0.0.1:8081/v1/chat/completions
```

Record:

- time to first byte
- total response time
- route target
- context status
- whether the response came through the full or fast gateway

The fast lane is useful only if it is materially closer to raw `8081` while
still preserving GlyphOS behavior.

## Troubleshooting

### CUDA host but no GPU runtime

Run:

```bash
llama-model doctor
llama-model build-runtime --backend cuda
```

The installer can install CUDA toolkit packages when accepted interactively.
If `nvcc` is missing on Debian/Ubuntu, install the toolkit package or rerun the
installer and accept dependency installation.

### Runtime built but not selected

Check:

```bash
llama-model doctor
cat ~/.config/llama-server/defaults.env
```

Runtime bundles live under:

```text
~/.local/share/llama-model-manager/runtime/llama-server/<os>-<arch>-<backend>/llama-server
```

### OpenCode says model not found

Run:

```bash
opencode models --refresh
llama-model sync-opencode
opencode models --refresh
```

Then verify that the agent config references model IDs that exist in the live
OpenCode catalog.

### oh-my-openagent still points elsewhere

Make sure the file exists before sync:

```bash
test -f ~/.config/opencode/oh-my-openagent.json
llama-model sync-opencode
```

Then inspect:

```bash
cat ~/.config/opencode/oh-my-openagent.json
```

Known agent entries should now prefer `glyphos-fast/<model>`.

### Gateway stream feels slow

Use the dashboard Gateway Trace panel and compare:

- context status
- encoding status
- route duration
- full lane `4010`
- fast lane `4011`
- raw backend `8081`

If `4011` is still slow, optional context preflight may still be too expensive
for the local machine or active model.

## Operator Rules

- Use `4010` for normal GlyphOS-routed traffic.
- Use `4011` for latency-sensitive GlyphOS-routed traffic.
- Use `8081` only for backend diagnostics or deliberate bypass.
- Keep cloud routing explicit.
- Refresh OpenCode models after provider changes.
- Sync OpenCode again after changing the active local model.
- Treat `~/.glyphos/config.yaml` as the active GlyphOS policy file.
