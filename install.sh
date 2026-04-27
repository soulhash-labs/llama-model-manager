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

mkdir -p "$BIN_DIR" "$CONFIG_DIR" "$APP_DIR" "$APP_SHARE_DIR"

install -m 0755 "$ROOT_DIR/bin/llama-model" "$BIN_DIR/llama-model"
install -m 0755 "$ROOT_DIR/bin/llama-model-gui" "$BIN_DIR/llama-model-gui"
install -m 0755 "$ROOT_DIR/bin/llama-model-web" "$BIN_DIR/llama-model-web"
install -m 0644 "$ROOT_DIR/config/HELP.txt" "$CONFIG_DIR/HELP.txt"
rm -rf "$APP_SHARE_DIR/web"
cp -a "$ROOT_DIR/web" "$APP_SHARE_DIR/web"
rm -rf "$APP_SHARE_DIR/scripts"
cp -a "$ROOT_DIR/scripts" "$APP_SHARE_DIR/scripts"
if [[ -d "$ROOT_DIR/integrations" ]]; then
    rm -rf "$APP_SHARE_DIR/integrations"
    cp -a "$ROOT_DIR/integrations" "$APP_SHARE_DIR/integrations"
fi
if [[ -d "$ROOT_DIR/runtime" ]]; then
    rm -rf "$APP_SHARE_DIR/runtime"
    cp -a "$ROOT_DIR/runtime" "$APP_SHARE_DIR/runtime"
fi
mkdir -p "$APP_SHARE_DIR/branding"
install -m 0644 "$ROOT_DIR/desktop/llama-model-manager-icon.svg" \
    "$APP_SHARE_DIR/branding/llama-model-manager-icon.svg"

if [[ ! -f "$CONFIG_DIR/defaults.env" ]]; then
    install -m 0644 "$ROOT_DIR/config/defaults.env.example" "$CONFIG_DIR/defaults.env"
    printf 'installed %s\n' "$CONFIG_DIR/defaults.env"
else
    printf 'kept existing %s\n' "$CONFIG_DIR/defaults.env"
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
