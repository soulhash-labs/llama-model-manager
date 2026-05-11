#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LLAMA_MODEL_BIN="$ROOT_DIR/bin/llama-model"

if [[ ! -x "$LLAMA_MODEL_BIN" ]]; then
    LLAMA_MODEL_BIN="${HOME}/.local/bin/llama-model"
fi

[[ -x "$LLAMA_MODEL_BIN" ]] || {
    printf 'llama-model not found: %s\n' "$LLAMA_MODEL_BIN" >&2
    exit 1
}

exec "$LLAMA_MODEL_BIN" build-runtime "$@"
