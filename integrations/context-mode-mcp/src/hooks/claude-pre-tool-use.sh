#!/usr/bin/env bash
set +e
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
ROOT_DIR="$(cd "$ROOT_DIR" && pwd)"
cd "$ROOT_DIR"
node dist/hooks/runner.js --category pre_tool_use "$@"
