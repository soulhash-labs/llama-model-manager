# Claude Code Local Gateway Note

Claude Code expects an Anthropic-compatible API, so it cannot point directly at the raw llama.cpp OpenAI-compatible endpoint.

## Local Pieces

- Claude settings file: `~/.claude/settings.json`
- Local gateway command:

```bash
llama-model claude-gateway start
llama-model claude-gateway status
llama-model claude-gateway logs
```

## Sync From LMM

```bash
llama-model sync-claude
llama-model sync-claude qwen35-9b-q8
```

## Defaults That Control The Gateway

- `CLAUDE_GATEWAY_HOST`
- `CLAUDE_GATEWAY_PORT`
- `CLAUDE_GATEWAY_LOG`
- `CLAUDE_BASE_URL`
- `CLAUDE_MODEL_ID`
- `CLAUDE_AUTH_TOKEN`
- `CLAUDE_API_KEY`

## Expected Local Flow

1. `llama-model switch <alias>`
2. `llama-model claude-gateway start`
3. `llama-model sync-claude`
4. point Claude Code at the local gateway through the synced settings

## Notes

- If `CLAUDE_API_KEY` is blank and `CLAUDE_AUTH_TOKEN` is set, LMM mirrors the auth token into the API key field for compatibility.
- The gateway advertises the configured Claude model id when one is set.
