#!/usr/bin/env bash
set -euo pipefail

# Main installer for Llama Model Manager.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${HOME}/.local/bin"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/llama-server"
APP_DIR="${HOME}/.local/share/applications"
APP_SHARE_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/llama-model-manager"
DESKTOP_DIR="${HOME}/Desktop"

write_empty_registry() {
    local target="$1"
    cat >"$target" <<'EOF_MODELS'
# alias<TAB>model_path<TAB>extra_args<TAB>context<TAB>ngl<TAB>batch<TAB>threads<TAB>parallel<TAB>device<TAB>notes
EOF_MODELS
}

is_placeholder_seed_registry() {
    local target="$1"
    [[ -f "$target" ]] || return 1

    local current_seed expected_seed
    current_seed="$(tr -d '\r' <"$target" | sed '/^[[:space:]]*$/d')"
    expected_seed="$(tr -d '\r' <"$ROOT_DIR/config/models.tsv.example" | sed '/^[[:space:]]*$/d')"
    [[ "$current_seed" == "$expected_seed" ]]
}

compact_home_path() {
    local value="$1"
    if [[ "$value" == "$HOME" ]]; then
        printf "~\n"
    elif [[ "$value" == "$HOME/"* ]]; then
        printf "~/%s\n" "${value#"$HOME/"}"
    else
        printf "%s\n" "$value"
    fi
}

clean_python_cache() {
    local target="$1"
    [[ -d "$target" ]] || return 0
    find "$target" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
    find "$target" -type f -name '*.pyc' -delete 2>/dev/null || true
}

# npm_hardened_ci — supply-chain safe npm install wrapper.
#
#   npm_hardened_ci omit  — Context MCP server bundle (no optional deps needed)
#   npm_hardened_ci keep  — Next/Vite/dashboard/frontend builds (need optional
#                           platform packages like SWC binaries)
npm_hardened_ci() {
    local optional_mode="${1:-omit}"
    [[ -f package-lock.json ]] || die "package-lock.json is required; refusing unlocked npm install"
    case "$optional_mode" in
        omit) npm ci --omit=optional --ignore-scripts --no-audit --fund=false ;;
        keep) npm ci --ignore-scripts --no-audit --fund=false ;;
        *)    die "unknown npm optional mode: $optional_mode" ;;
    esac
}

die() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

# safe_install — portable replacement for `install -m` (GNU coreutils).
# Falls back to cp + chmod on minimal systems (Alpine, stripped containers).
safe_install() {
    local mode="$1"
    local src="$2"
    local dest="$3"
    if command -v install >/dev/null 2>&1; then
        install -m "$mode" "$src" "$dest"
    else
        cp "$src" "$dest"
        chmod "$mode" "$dest"
    fi
}

ensure_context_mode_mcp_dist() {
    local mcp_dir="$ROOT_DIR/integrations/context-mode-mcp"

    [[ -f "$mcp_dir/package.json" ]] || return 0
    [[ -f "$mcp_dir/dist/index.js" ]] && return 0

    if ! command -v npm >/dev/null 2>&1; then
        printf 'post-install warning: Context Mode MCP dist/index.js is missing and npm is unavailable; Context MCP will remain degraded until you run npm ci --ignore-scripts && npm run build:mcp in %s\n' "$mcp_dir" >&2
        return 0
    fi
    if [[ ! -f "$mcp_dir/package-lock.json" ]]; then
        printf 'post-install warning: Context Mode MCP package-lock.json is missing; refusing live npm resolution during install. Context MCP will remain degraded until a locked package is available in %s\n' "$mcp_dir" >&2
        return 0
    fi

    printf 'building Context Mode MCP server bundle...\n'
    if (
        cd "$mcp_dir"
        npm_hardened_ci omit
        npm run build:mcp
    ); then
        printf 'built Context Mode MCP server bundle\n'
    else
        printf 'post-install warning: failed to build Context Mode MCP server bundle; Context MCP will remain degraded until you run npm ci --ignore-scripts && npm run build:mcp in %s\n' "$mcp_dir" >&2
    fi
}

defaults_has_key() {
    local key="$1"
    local file="$2"
    grep -Eq "^[[:space:]]*(export[[:space:]]+)?${key}=" "$file"
}

default_value() {
    local key="$1"
    local fallback="$2"
    local file="$CONFIG_DIR/defaults.env"

    if [[ ! -f "$file" ]]; then
        printf '%s\n' "$fallback"
        return 0
    fi
    python3 - "$file" "$key" "$fallback" <<'PY'
import shlex
import sys
from pathlib import Path

path = Path(sys.argv[1])
key = sys.argv[2]
fallback = sys.argv[3]
value = ""

for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        continue
    try:
        parts = shlex.split(stripped, comments=True, posix=True)
    except ValueError:
        continue
    if not parts:
        continue
    if parts[0] == "export":
        parts = parts[1:]
    for part in parts:
        if part.startswith(f"{key}="):
            value = part.split("=", 1)[1]

print(value or fallback)
PY
}

read_saved_current_model() {
    local state_file="$1"
    [[ -f "$state_file" ]] || return 1
    python3 - "$state_file" <<'PY'
import shlex
import sys
from pathlib import Path

path = Path(sys.argv[1])
for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
    stripped = line.strip()
    if not stripped.startswith("CURRENT_MODEL="):
        continue
    try:
        parts = shlex.split(stripped, posix=True)
    except ValueError:
        raise SystemExit(1)
    if len(parts) == 1 and parts[0].startswith("CURRENT_MODEL="):
        print(parts[0].split("=", 1)[1])
        raise SystemExit(0)
raise SystemExit(1)
PY
}

migrate_routed_gateway_defaults() {
    local file="$CONFIG_DIR/defaults.env"
    local changed="no"
    local backup=""
    local tmp=""

    [[ -f "$file" ]] || return 0

    if grep -Eq '^[[:space:]]*(export[[:space:]]+)?LLAMA_MODEL_OPENCODE_GATEWAY_BASE_URL=' "$file"; then
        changed="yes"
    fi
    for key in LLAMA_MODEL_HARNESS_MODE LLAMA_MODEL_GATEWAY_HOST LLAMA_MODEL_GATEWAY_PORT LLAMA_MODEL_GATEWAY_LOG; do
        if ! defaults_has_key "$key" "$file"; then
            changed="yes"
        fi
    done
    [[ "$changed" == "yes" ]] || return 0

    backup="${file}.bak.$(date -u +%Y%m%dT%H%M%SZ)"
    cp "$file" "$backup"
    tmp="${file}.tmp.$$"
    grep -Ev '^[[:space:]]*(export[[:space:]]+)?LLAMA_MODEL_OPENCODE_GATEWAY_BASE_URL=' "$backup" >"$tmp" || true
    if ! defaults_has_key LLAMA_MODEL_HARNESS_MODE "$tmp"; then
        printf '\n# Harness routing. Routed mode points OpenAI-compatible clients at the LMM gateway.\n' >>"$tmp"
        printf 'LLAMA_MODEL_HARNESS_MODE=routed\n' >>"$tmp"
    fi
    if ! defaults_has_key LLAMA_MODEL_GATEWAY_HOST "$tmp"; then
        printf 'LLAMA_MODEL_GATEWAY_HOST=127.0.0.1\n' >>"$tmp"
    fi
    if ! defaults_has_key LLAMA_MODEL_GATEWAY_PORT "$tmp"; then
        printf 'LLAMA_MODEL_GATEWAY_PORT=4010\n' >>"$tmp"
    fi
    if ! defaults_has_key LLAMA_MODEL_GATEWAY_LOG "$tmp"; then
        printf 'LLAMA_MODEL_GATEWAY_LOG=$HOME/models/lmm-gateway.log\n' >>"$tmp"
    fi
    mv "$tmp" "$file"
    printf 'migrated routed gateway defaults in %s\n' "$(compact_home_path "$file")"
    printf 'backup: %s\n' "$(compact_home_path "$backup")"
}

post_install_sync_clients() {
    local synced="no"
    local opencode_config="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.json"
    local openclaw_config="$HOME/.openclaw/openclaw.json"
    local glyphos_config="$HOME/.glyphos/config.yaml"
    local state_file="${XDG_STATE_HOME:-$HOME/.local/state}/llama-server/current.env"
    local saved_model=""
    local backend_health_url=""
    local profile_dir=""
    local profile_name=""

    if [[ -f "$state_file" ]]; then
        saved_model="$(read_saved_current_model "$state_file" 2>/dev/null || true)"
    fi
    backend_health_url="http://$(default_value LLAMA_SERVER_HOST 127.0.0.1):$(default_value LLAMA_SERVER_PORT 8081)/health"
    if ! curl -fsS --max-time 1 "$backend_health_url" >/dev/null 2>&1 && { [[ -z "$saved_model" ]] || [[ ! -f "$saved_model" ]]; }; then
        printf 'post-install sync skipped: no running backend or saved current model is resolvable yet\n'
        return 0
    fi

    if [[ -f "$opencode_config" ]]; then
        if "$BIN_DIR/llama-model" sync-opencode >/dev/null 2>&1; then
            printf 'post-install synced opencode to routed gateway\n'
            synced="yes"
        else
            printf 'post-install warning: opencode sync failed; start or switch a model, then run llama-model sync-opencode\n' >&2
        fi
    fi
    if [[ -f "$openclaw_config" ]]; then
        if "$BIN_DIR/llama-model" sync-openclaw >/dev/null 2>&1; then
            printf 'post-install synced OpenClaw to routed gateway\n'
            synced="yes"
        else
            printf 'post-install warning: OpenClaw sync failed; start or switch a model, then run llama-model sync-openclaw\n' >&2
        fi
    fi
    local nullglob_was_set="no"
    if shopt -q nullglob; then
        nullglob_was_set="yes"
    fi
    shopt -s nullglob
    for profile_dir in "$HOME"/.openclaw-*; do
        [[ -f "$profile_dir/openclaw.json" ]] || continue
        profile_name="${profile_dir##*/.openclaw-}"
        [[ -n "$profile_name" ]] || continue
        if "$BIN_DIR/llama-model" sync-openclaw --profile "$profile_name" >/dev/null 2>&1; then
            printf 'post-install synced OpenClaw profile %s to routed gateway\n' "$profile_name"
            synced="yes"
        else
            printf 'post-install warning: OpenClaw profile %s sync failed; start or switch a model, then run llama-model sync-openclaw --profile %s\n' "$profile_name" "$profile_name" >&2
        fi
    done
    if [[ "$nullglob_was_set" == "yes" ]]; then
        shopt -s nullglob
    else
        shopt -u nullglob
    fi
    if [[ -f "$glyphos_config" ]]; then
        if "$BIN_DIR/llama-model" sync-glyphos >/dev/null 2>&1; then
            printf 'post-install synced GlyphOS to the backend endpoint\n'
            synced="yes"
        else
            printf 'post-install warning: GlyphOS sync failed; start or switch a model, then run llama-model sync-glyphos\n' >&2
        fi
    fi
    [[ "$synced" == "yes" ]] || printf 'post-install sync skipped: no existing opencode, OpenClaw, or GlyphOS configs found\n'
}

require_source_tree() {
    local missing=0

    [[ -f "$ROOT_DIR/web/app.py" ]] || {
        printf 'error: installer payload is missing web/app.py\n' >&2
        missing=1
    }
    [[ -f "$ROOT_DIR/scripts/integration_sync.py" ]] || {
        printf 'error: installer payload is missing scripts/integration_sync.py\n' >&2
        missing=1
    }
    [[ -f "$ROOT_DIR/scripts/glyphos_openai_gateway.py" ]] || {
        printf 'error: installer payload is missing scripts/glyphos_openai_gateway.py\n' >&2
        missing=1
    }
    [[ -f "$ROOT_DIR/scripts/context_mcp_bridge.py" ]] || {
        printf 'error: installer payload is missing scripts/context_mcp_bridge.py\n' >&2
        missing=1
    }
    [[ -d "$ROOT_DIR/integrations/public-glyphos-ai-compute/glyphos_ai" ]] || {
        printf 'error: installer payload is missing integrations/public-glyphos-ai-compute/glyphos_ai\n' >&2
        missing=1
    }
    [[ -f "$ROOT_DIR/integrations/context-mode-mcp/package.json" ]] || {
        printf 'error: installer payload is missing integrations/context-mode-mcp/package.json\n' >&2
        missing=1
    }

    if [[ "$missing" -ne 0 ]]; then
        printf 'error: download the full llama-model-manager archive and rerun install.sh\n' >&2
        exit 1
    fi
}

require_source_tree
ensure_context_mode_mcp_dist
mkdir -p "$BIN_DIR" "$CONFIG_DIR" "$APP_DIR" "$APP_SHARE_DIR"

safe_install 0755 "$ROOT_DIR/bin/llama-model" "$BIN_DIR/llama-model"
safe_install 0755 "$ROOT_DIR/bin/llama-model-gui" "$BIN_DIR/llama-model-gui"
safe_install 0755 "$ROOT_DIR/bin/llama-model-web" "$BIN_DIR/llama-model-web"
safe_install 0644 "$ROOT_DIR/config/HELP.txt" "$CONFIG_DIR/HELP.txt"
rm -rf "$APP_SHARE_DIR/web"
cp -a "$ROOT_DIR/web" "$APP_SHARE_DIR/web"
rm -rf "$APP_SHARE_DIR/scripts"
cp -a "$ROOT_DIR/scripts" "$APP_SHARE_DIR/scripts"
chmod 0755 "$APP_SHARE_DIR/scripts/glyphos_openai_gateway.py" "$APP_SHARE_DIR/scripts/context_mcp_bridge.py" "$APP_SHARE_DIR/scripts/integration_sync.py" 2>/dev/null || true
rm -rf "$APP_SHARE_DIR/integrations"
cp -a "$ROOT_DIR/integrations" "$APP_SHARE_DIR/integrations"
clean_python_cache "$APP_SHARE_DIR/integrations"
printf 'refreshed bundled integrations under %s/integrations\n' "$(compact_home_path "$APP_SHARE_DIR")"
if [[ -d "$ROOT_DIR/runtime" ]]; then
    rm -rf "$APP_SHARE_DIR/runtime"
    cp -a "$ROOT_DIR/runtime" "$APP_SHARE_DIR/runtime"
fi
mkdir -p "$APP_SHARE_DIR/branding"
safe_install 0644 "$ROOT_DIR/desktop/llama-model-manager-icon.svg" \
    "$APP_SHARE_DIR/branding/llama-model-manager-icon.svg"

if [[ ! -f "$CONFIG_DIR/defaults.env" ]]; then
    safe_install 0644 "$ROOT_DIR/config/defaults.env.example" "$CONFIG_DIR/defaults.env"
    printf 'installed %s\n' "$CONFIG_DIR/defaults.env"
else
    printf 'kept existing %s\n' "$CONFIG_DIR/defaults.env"
    migrate_routed_gateway_defaults
    if ! grep -Eq '^[[:space:]]*GGML_CUDA_ENABLE_UNIFIED_MEMORY=' "$CONFIG_DIR/defaults.env"; then
        printf 'note: existing defaults.env does not include the experimental CUDA unified-memory toggle\n'
        printf 'note: add GGML_CUDA_ENABLE_UNIFIED_MEMORY=1 to %s/defaults.env if you want to test RAM fallback for oversized CUDA context/KV allocations\n' "$(compact_home_path "$CONFIG_DIR")"
        printf 'note: this may be slower on discrete GPUs and should usually be paired with LLAMA_SERVER_PARALLEL=1\n'
    fi
fi

if [[ ! -f "$CONFIG_DIR/models.tsv" ]]; then
    write_empty_registry "$CONFIG_DIR/models.tsv"
    printf 'installed %s\n' "$CONFIG_DIR/models.tsv"
elif is_placeholder_seed_registry "$CONFIG_DIR/models.tsv"; then
    write_empty_registry "$CONFIG_DIR/models.tsv"
    printf 'migrated %s\n' "$CONFIG_DIR/models.tsv"
else
    printf 'kept existing %s\n' "$CONFIG_DIR/models.tsv"
fi
sed -e "s|^Exec=.*$|Exec=$BIN_DIR/llama-model-gui|" \
    -e "s|^Icon=.*$|Icon=$APP_SHARE_DIR/branding/llama-model-manager-icon.svg|" \
    "$ROOT_DIR/desktop/llama-model-manager.desktop" >"$APP_DIR/llama-model-manager.desktop"
chmod 0644 "$APP_DIR/llama-model-manager.desktop"

if [[ -d "$DESKTOP_DIR" ]]; then
    sed -e "s|^Exec=.*$|Exec=$BIN_DIR/llama-model-gui|" \
        -e "s|^Icon=.*$|Icon=$APP_SHARE_DIR/branding/llama-model-manager-icon.svg|" \
        "$ROOT_DIR/desktop/llama-model-manager.desktop" >"$DESKTOP_DIR/Llama Model Manager.desktop"
    chmod 0755 "$DESKTOP_DIR/Llama Model Manager.desktop"
fi

post_install_sync_clients

printf '\nInstalled llama-model-manager.\n'
printf 'Next steps:\n'
printf '  1. Open the dashboard: llama-model-web\n'
printf '  2. Or use the launcher: llama-model-gui\n'
printf '  3. Build a local runtime if needed: llama-model build-runtime --backend auto\n'
printf '  4. Edit %s/defaults.env if needed\n' "$(compact_home_path "$CONFIG_DIR")"
printf '  5. Run: llama-model current\n'
OPENCODE_CONFIG_FILE="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.json"
OPENCLAW_MAIN_CONFIG="$HOME/.openclaw/openclaw.json"
CLAUDE_SETTINGS_FILE="$HOME/.claude/settings.json"
if [[ -f "$OPENCODE_CONFIG_FILE" ]]; then
    printf '  6. Sync your existing opencode config: llama-model sync-opencode\n'
else
    printf '  6. If you use opencode later, sync it with: llama-model sync-opencode\n'
fi
if [[ -f "$OPENCLAW_MAIN_CONFIG" ]]; then
    printf '  7. Sync your existing OpenClaw config: llama-model sync-openclaw\n'
else
    printf '  7. If you use OpenClaw later, sync it with: llama-model sync-openclaw\n'
fi
if [[ -f "$CLAUDE_SETTINGS_FILE" ]]; then
    printf '  8. Sync your Claude Code settings: llama-model sync-claude\n'
else
    printf '  8. If you use Claude Code later, sync it with: llama-model sync-claude\n'
fi
printf '  9. Optional local Claude gateway: llama-model claude-gateway start\n'
printf ' 10. Sync GlyphOS AI Compute if you use it: llama-model sync-glyphos\n'
printf ' 11. Bundled public GlyphOS AI Compute package: %s/integrations/public-glyphos-ai-compute\n' "$(compact_home_path "$APP_SHARE_DIR")"
printf ' 12. Experimental CUDA unified-memory fallback: set GGML_CUDA_ENABLE_UNIFIED_MEMORY=1 in %s/defaults.env to try larger context/KV/compute allocations through system RAM\n' "$(compact_home_path "$CONFIG_DIR")"
printf '     on discrete GPUs this can be much slower; usually pair it with LLAMA_SERVER_PARALLEL=1\n'
printf 'Routing endpoints:\n'
printf '  harness endpoint: http://%s:%s/v1\n' "$(default_value LLAMA_MODEL_GATEWAY_HOST 127.0.0.1)" "$(default_value LLAMA_MODEL_GATEWAY_PORT 4010)"
printf '  backend endpoint: http://%s:%s/v1\n' "$(default_value LLAMA_SERVER_HOST 127.0.0.1)" "$(default_value LLAMA_SERVER_PORT 8081)"
printf '  default route mode: LLAMA_MODEL_HARNESS_MODE=%s\n' "$(default_value LLAMA_MODEL_HARNESS_MODE routed)"

if [[ -t 0 && -t 1 ]]; then
    printf '\nWould you like to check/install build dependencies and compile a local llama.cpp runtime now? [Y/n] '
    read -r reply || reply=""
    reply="${reply,,}"
    if [[ -z "$reply" || "$reply" == "y" || "$reply" == "yes" ]]; then
        if "$BIN_DIR/llama-model" build-runtime --backend auto; then
            printf 'Local runtime build completed.\n'
        else
            printf 'Runtime build did not complete. Resolve any missing dependencies and rerun: llama-model build-runtime --backend auto\n' >&2
        fi
    fi
fi
