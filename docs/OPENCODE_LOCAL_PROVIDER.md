# OpenCode Local Provider Note

This note records a local integration issue that can look like a broken llama.cpp server even when the local runtime is healthy.

## Symptom

- `opencode` does not list or use the local llama model
- the local llama server is already healthy at:
  - `http://127.0.0.1:8081/v1`

## Root Cause

OpenCode will not discover a local llama.cpp / OpenAI-compatible endpoint unless a provider is configured explicitly.

A machine can have:

- a healthy local llama server
- a reachable model endpoint
- no OpenCode provider configuration

and still appear as if "opencode cannot see llama".

## Fix

Create the OpenCode config file at:

- `~/.config/opencode/opencode.json`

and define a provider using the documented OpenAI-compatible provider path.

Example:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "llama.cpp": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "llama-server (local)",
      "options": {
        "baseURL": "http://127.0.0.1:8081/v1",
        "timeout": 600000,
        "chunkTimeout": 60000
      },
      "models": {
        "Qwen3.5-2B=Q4_K_M.gguf": {
          "name": "Qwen3.5-2B Q4_K_M (local)",
          "limit": {
            "context": 32000,
            "output": 4096
          }
        }
      }
    }
  },
  "model": "llama.cpp/Qwen3.5-2B=Q4_K_M.gguf",
  "small_model": "llama.cpp/Qwen3.5-2B=Q4_K_M.gguf"
}
```

## Verification

Once configured, this should work:

```bash
opencode models llama.cpp
```

Expected result:

- `llama.cpp/Qwen3.5-2B=Q4_K_M.gguf`

## Scope Note

This is a local machine integration note.
It is not a `llama-model-manager` runtime bug by itself.

## References

- `https://opencode.ai/docs/config`
- `https://opencode.ai/docs/providers/`
