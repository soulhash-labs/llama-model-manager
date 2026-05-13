#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv-smoke}"
WHEEL_PATH="${WHEEL_PATH:-}"

echo "==> Cleaning previous smoke venv"
rm -rf "$VENV_DIR"

echo "==> Creating smoke venv"
"$PYTHON_BIN" -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

echo "==> Upgrading pip/build tools"
python -m pip install --upgrade pip setuptools wheel build

echo "==> Building wheel"
python -m build

if [[ -z "$WHEEL_PATH" ]]; then
  WHEEL_PATH="$(ls -1 dist/*.whl | tail -n 1)"
fi

if [[ ! -f "$WHEEL_PATH" ]]; then
  echo "❌ Wheel not found: $WHEEL_PATH"
  exit 1
fi

echo "==> Installing wheel: $WHEEL_PATH"
python -m pip install "$WHEEL_PATH"

echo "==> Smoke 1: entry point exists"
command -v glyphos-route >/dev/null 2>&1 || {
  echo "❌ glyphos-route entry point not found after install"
  exit 1
}

echo "==> Smoke 2: status command"
STATUS_JSON="$(glyphos-route --status --json)"
python - <<'PY' "$STATUS_JSON"
import json, sys
payload = json.loads(sys.argv[1])
assert "preferred_local_backend" in payload, payload
assert "available_backends" in payload, payload
assert isinstance(payload["available_backends"], dict), payload
print("✅ status payload OK")
PY

echo "==> Smoke 3: structured packet route without context"
ROUTE_JSON="$(glyphos-route \
  --action QUERY \
  --destination MODEL \
  --psi 0.8 \
  --time-slot 7 \
  --show-prompt \
  --show-structured \
  --json
)"
python - <<'PY' "$ROUTE_JSON"
import json, sys
payload = json.loads(sys.argv[1])
assert payload["packet"], payload
assert payload["decoded_packet"]["action"] == "QUERY", payload
assert payload["decoded_packet"]["destination"] == "MODEL", payload
assert payload["target"], payload
assert payload["routing_reason"], payload
assert payload["response"] is not None, payload
assert "[CONTEXT_ANCHOR]" not in payload["prompt"], payload["prompt"]
assert payload["structured"]["intent"]["action"] == "QUERY", payload
assert payload["structured"]["context"]["upstream_context_present"] is False, payload
print("✅ route without context OK")
PY

echo "==> Smoke 4: structured packet route with explicit upstream context"
CTX_JSON='{"content":"LANE_STATE(AURORA): healthy","locality":"orion-local","routing_hints":{"preferred_backend":"llamacpp","token_budget":2048},"provenance":["aurora-health","ops-heartbeat"]}'

ROUTE_CTX_JSON="$(glyphos-route \
  --action QUERY \
  --destination MODEL \
  --psi 0.8 \
  --time-slot 7 \
  --upstream-context-json "$CTX_JSON" \
  --show-prompt \
  --show-structured \
  --json
)"
python - <<'PY' "$ROUTE_CTX_JSON"
import json, sys
payload = json.loads(sys.argv[1])
assert payload["upstream_context_provided"] is True, payload
assert "[CONTEXT_ANCHOR]" in payload["prompt"], payload["prompt"]
assert "LANE_STATE(AURORA): healthy" in payload["prompt"], payload["prompt"]
structured = payload["structured"]
assert structured["context"]["upstream_context_present"] is True, structured
assert structured["context"]["upstream"]["locality"] == "orion-local", structured
assert structured["routing"]["preferred_backend"] == "llamacpp", structured
assert structured["routing"]["preferred_backend_source"] == "routing_hints", structured
print("✅ route with context OK")
PY

echo "==> Smoke 5: import surface"
python - <<'PY'
from glyphos_ai import AdaptiveRouter, ContextPacket, GlyphPacket, glyph_to_prompt, load_registry
packet = GlyphPacket(instance_id="abc123", psi_coherence=0.8, action="QUERY", time_slot="T07", destination="MODEL")
ctx: ContextPacket = {"content": "LANE_STATE(AURORA): healthy", "locality": "orion-local"}
prompt = glyph_to_prompt(packet, upstream_context=ctx)
assert "[CONTEXT_ANCHOR]" in prompt
registry = load_registry()
assert len(registry) == 256
print("✅ import surface OK")
PY

echo "🎉 Installed wheel smoke test passed"
