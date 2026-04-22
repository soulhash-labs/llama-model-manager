# OpenClaw Local Provider Note

OpenClaw can target the local llama.cpp server directly through its OpenAI-compatible provider support.

## Config Path

- main profile: `~/.openclaw/openclaw.json`
- named profile: `~/.openclaw-<profile>/openclaw.json`

## Sync From LMM

```bash
llama-model sync-openclaw
llama-model sync-openclaw --profile lmm-eval qwen35-9b-q8
```

## What Sync Updates

- `agents.defaults.model.primary`
- `agents.defaults.models["llamacpp/<model-id>"]`
- `models.providers.llamacpp.baseUrl`
- `models.providers.llamacpp.apiKey`
- `models.providers.llamacpp.api`
- `models.providers.llamacpp.models[]`

## Default Endpoint

- `http://127.0.0.1:8081/v1`

## Notes

- OpenClaw does not need the Claude-style compatibility gateway.
- LMM preserves unrelated OpenClaw settings and providers when syncing.
