#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"
node "$ROOT_DIR/dist/hooks/runner.js" --category session_start --session-id "${CTX_SESSION_ID:-}" --project-root "${CTX_PROJECT_ROOT:-}"
