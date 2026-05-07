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

install_basedpyright_during_install() {
    if [[ ! -t 0 || ! -t 1 ]]; then
        return 0
    fi
    if command -v basedpyright >/dev/null 2>&1; then
        printf 'post-install: basedpyright already available\n'
        return 0
    fi
    printf 'Install basedpyright for local Python type diagnostics? [Y/n] '
    local reply
    read -r reply || reply=""
    reply="${reply,,}"
    if [[ "$reply" == "n" || "$reply" == "no" ]]; then
        printf 'post-install: basedpyright install skipped by user\n'
        return 0
    fi

    if ! command -v pipx >/dev/null 2>&1; then
        printf 'post-install: pipx is required for basedpyright on externally-managed Python environments\n'
        if command -v apt-get >/dev/null 2>&1; then
            printf 'post-install: installing pipx with apt\n'
            if [[ "$EUID" -eq 0 ]]; then
                apt-get update && apt-get install -y pipx
            elif command -v sudo >/dev/null 2>&1; then
                sudo apt-get update && sudo apt-get install -y pipx
            else
                printf 'post-install: sudo not available; install pipx manually with: sudo apt install pipx\n' >&2
            fi
        else
            printf 'post-install: install pipx with your OS package manager, then run: pipx install basedpyright\n' >&2
        fi
    fi

    if command -v pipx >/dev/null 2>&1; then
        pipx ensurepath || true
        if pipx install basedpyright; then
            printf 'post-install: basedpyright installed with pipx\n'
        else
            printf 'post-install: basedpyright install failed; retry manually with: pipx install basedpyright\n' >&2
        fi
    else
        printf 'post-install: basedpyright install skipped; retry manually with: sudo apt install pipx && pipx ensurepath && pipx install basedpyright\n' >&2
    fi
}

recommended_opencode_install_command() {
    local os
    os="$(uname -s)"
    if [[ "$os" == "Darwin" ]] && command -v brew >/dev/null 2>&1; then
        printf 'brew install anomalyco/tap/opencode\n'
    elif command -v paru >/dev/null 2>&1; then
        printf 'paru -S opencode\n'
    elif command -v bun >/dev/null 2>&1; then
        printf 'bun add -g opencode-ai\n'
    elif command -v npm >/dev/null 2>&1; then
        printf 'npm i -g opencode-ai\n'
    else
        printf 'curl -fsSL https://opencode.ai/install | bash\n'
    fi
}

run_opencode_install_command() {
    local command_text="$1"
    case "$command_text" in
        "curl -fsSL https://opencode.ai/install | bash")
            curl -fsSL https://opencode.ai/install | bash
            ;;
        "npm i -g opencode-ai")
            npm i -g opencode-ai
            ;;
        "bun add -g opencode-ai")
            bun add -g opencode-ai
            ;;
        "brew install anomalyco/tap/opencode")
            brew install anomalyco/tap/opencode
            ;;
        "paru -S opencode")
            paru -S opencode
            ;;
        *)
            printf 'post-install: unknown OpenCode install command: %s\n' "$command_text" >&2
            return 1
            ;;
    esac
}

recommended_oh_my_openagent_install_command() {
    if command -v bunx >/dev/null 2>&1; then
        printf 'bunx oh-my-openagent install\n'
    elif command -v npx >/dev/null 2>&1; then
        printf 'npx oh-my-openagent install\n'
    elif command -v npm >/dev/null 2>&1; then
        printf 'npx oh-my-openagent install\n'
    else
        printf ''
    fi
}

run_oh_my_openagent_install_command() {
    local command_text="$1"
    case "$command_text" in
        "bunx oh-my-openagent install")
            if command -v bunx >/dev/null 2>&1; then
                bunx oh-my-openagent install
            else
                printf 'post-install: bunx is unavailable\n' >&2
                return 1
            fi
            ;;
        "npx oh-my-openagent install")
            if command -v npx >/dev/null 2>&1; then
                npx oh-my-openagent install
            else
                printf 'post-install: npx is unavailable\n' >&2
                return 1
            fi
            ;;
        *)
            printf 'post-install: unknown oh-my-openagent install command: %s\n' "$command_text" >&2
            return 1
            ;;
    esac
}

fetch_oh_my_openagent_guide() {
    local guide_url="$1"
    local guide_path="$2"

    if command -v curl >/dev/null 2>&1; then
        mkdir -p "$(dirname "$guide_path")"
        if curl -fsSL "$guide_url" -o "$guide_path"; then
            printf 'post-install: saved oh-my-openagent installation guide to %s\n' "$guide_path"
            return 0
        fi
        printf 'post-install warning: failed to fetch guide; open manually: %s\n' "$guide_url" >&2
        return 1
    fi

    printf 'post-install: curl unavailable; open this guide manually:\n  %s\n' "$guide_url" >&2
    return 1
}

path_state() {
    if [[ -e "$1" ]]; then
        printf 'present'
    else
        printf 'missing'
    fi
}

interactive_harness_setup_wizard() {
    local opencode_config="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/opencode.json"
    local openagent_config="${XDG_CONFIG_HOME:-$HOME/.config}/opencode/oh-my-openagent.json"
    local glyphos_config="$HOME/.glyphos/config.yaml"
    local guide_url="https://raw.githubusercontent.com/code-yeongyu/oh-my-openagent/refs/heads/dev/docs/guide/installation.md"
    local guide_path="$APP_SHARE_DIR/docs/oh-my-openagent-installation.md"
    local recommendation=""
    local openagent_recommendation=""
    local reply=""

    if [[ ! -t 0 || ! -t 1 ]]; then
        return 0
    fi

    printf '\nIntegration setup check:\n'
    printf '  installed CLI: %s (%s)\n' "$BIN_DIR/llama-model" "$(path_state "$BIN_DIR/llama-model")"
    printf '  installed assets: %s (%s)\n' "$APP_SHARE_DIR" "$(path_state "$APP_SHARE_DIR")"
    printf '  integration bundle: %s (%s)\n' "$APP_SHARE_DIR/integrations/public-glyphos-ai-compute" "$(path_state "$APP_SHARE_DIR/integrations/public-glyphos-ai-compute")"
    printf '  LMM defaults: %s (%s)\n' "$CONFIG_DIR/defaults.env" "$(path_state "$CONFIG_DIR/defaults.env")"
    printf '  LMM model registry: %s (%s)\n' "$CONFIG_DIR/models.tsv" "$(path_state "$CONFIG_DIR/models.tsv")"
    printf '  OpenCode config: %s (%s)\n' "$opencode_config" "$(path_state "$opencode_config")"
    printf '  oh-my-openagent config: %s (%s)\n' "$openagent_config" "$(path_state "$openagent_config")"
    printf '  GlyphOS policy: %s (%s)\n' "$glyphos_config" "$(path_state "$glyphos_config")"

    if command -v opencode >/dev/null 2>&1; then
        printf 'post-install: opencode already available\n'
    else
        recommendation="$(recommended_opencode_install_command)"
        printf 'post-install: opencode is not installed or not on PATH\n'
        printf 'Recommended install command for this machine:\n'
        printf '  %s\n' "$recommendation"
        printf 'Other supported OpenCode install options:\n'
        printf '  curl -fsSL https://opencode.ai/install | bash\n'
        printf '  npm i -g opencode-ai\n'
        printf '  bun add -g opencode-ai\n'
        printf '  brew install anomalyco/tap/opencode\n'
        printf '  paru -S opencode\n'
        printf 'Install OpenCode now with the recommended command? [Y/n] '
        read -r reply || reply=""
        reply="${reply,,}"
        if [[ "$reply" != "n" && "$reply" != "no" ]]; then
            if run_opencode_install_command "$recommendation"; then
                printf 'post-install: OpenCode install command completed\n'
            else
                printf 'post-install warning: OpenCode install command failed; retry manually with: %s\n' "$recommendation" >&2
            fi
        fi
    fi

    if [[ -f "$openagent_config" ]]; then
        printf 'post-install: oh-my-openagent config found: %s\n' "$openagent_config"
    else
        printf 'post-install: oh-my-openagent config missing: %s\n' "$openagent_config"
        printf 'Fetch the oh-my-openagent installation guide now? [Y/n] '
        read -r reply || reply=""
        reply="${reply,,}"
        if [[ "$reply" != "n" && "$reply" != "no" ]]; then
            fetch_oh_my_openagent_guide "$guide_url" "$guide_path" || true
        fi

        openagent_recommendation="$(recommended_oh_my_openagent_install_command)"
        if [[ -z "$openagent_recommendation" ]]; then
            printf 'post-install: cannot install oh-my-openagent automatically because bunx/npx is unavailable\n' >&2
            printf 'post-install: install Bun or Node.js, then run: bunx oh-my-openagent install\n' >&2
            return 0
        fi

        printf 'Recommended oh-my-openagent install command for this machine:\n'
        printf '  %s\n' "$openagent_recommendation"
        printf 'Other supported oh-my-openagent install option:\n'
        printf '  npx oh-my-openagent install\n'
        printf 'Install oh-my-openagent now with the recommended command? [Y/n] '
        read -r reply || reply=""
        reply="${reply,,}"
        if [[ "$reply" != "n" && "$reply" != "no" ]]; then
            if run_oh_my_openagent_install_command "$openagent_recommendation"; then
                printf 'post-install: oh-my-openagent installer completed\n'
                if "$BIN_DIR/llama-model" sync-opencode >/dev/null 2>&1; then
                    printf 'post-install: synced OpenCode and oh-my-openagent to LMM GlyphOS providers\n'
                else
                    printf 'post-install warning: sync-opencode failed; retry after selecting a model: llama-model sync-opencode\n' >&2
                fi
            else
                printf 'post-install warning: oh-my-openagent install failed; retry manually with: %s\n' "$openagent_recommendation" >&2
            fi
        fi
    fi
}

# build_runtime_during_install — auto-build a bundled llama.cpp runtime after
# the installer binaries are in place.  Replaces the old interactive-only prompt
# at the end of the script so fresh installs get GPU offload out of the box.
#
# Behaviour:
#   - Detects host OS/arch/backends using the installed `llama-model doctor`
#   - If a GPU backend (cuda/vulkan/metal) is available on the host, attempts
#     to build that backend + CPU fallback automatically
#   - Silently degrades to CPU-only if GPU build dependencies are missing
#   - Never blocks; build failures are logged, not fatal
build_runtime_during_install() {
    local bin="$BIN_DIR/llama-model"
    [[ -x "$bin" ]] || { printf 'post-install: skipping runtime build — %s not installed yet\n' "$bin" >&2; return 0; }

    printf 'post-install: detecting host GPU capabilities for runtime build...\n'

    # Fast-path: check for any GPU runtime signal.  We probe for the common
    # indicators that detect_host_backends() would use, without invoking
    # the full doctor output.
    local has_gpu="no"
    local primary_backend=""
    local os
    os="$(uname -s)"

    case "$os" in
        Linux)
            if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
                has_gpu="yes"
                primary_backend="cuda"
            elif ldconfig -p 2>/dev/null | grep -q 'libvulkan\.so'; then
                has_gpu="yes"
                primary_backend="vulkan"
            fi
            ;;
        Darwin)
            # macOS always has Metal if it's Apple Silicon or recent Intel
            has_gpu="yes"
            primary_backend="metal"
            ;;
    esac

    if [[ "$has_gpu" != "yes" ]]; then
        printf 'post-install: no GPU runtime detected on this host; building CPU fallback only\n'
        primary_backend="cpu"
    fi

    if [[ -t 0 && -t 1 ]]; then
        # Interactive: show what we're doing and ask
        printf 'post-install: host %s backend detected\n' "$primary_backend"
        if [[ "$primary_backend" == "cuda" ]] && ! command -v nvcc >/dev/null 2>&1; then
            printf 'post-install: CUDA host detected but nvcc is not in PATH\n'
            printf 'post-install: installer will attempt to install CUDA toolkit packages before compiling the CUDA runtime\n'
        fi
        printf 'Would you like to check/install build dependencies and compile a local llama.cpp runtime now? [Y/n] '
        local reply
        read -r reply || reply=""
        reply="${reply,,}"
        if [[ "$reply" == "n" || "$reply" == "no" ]]; then
            printf 'post-install: runtime build skipped by user\n'
            return 0
        fi
    else
        # Non-interactive / headless: only auto-build if deps are trivially
        # available (no sudo prompts, no user interaction needed).
        if [[ "$primary_backend" == "cpu" ]]; then
            printf 'post-install: non-interactive install on CPU-only host; building CPU runtime\n'
        elif [[ "$primary_backend" == "cuda" ]] && ! command -v nvcc >/dev/null 2>&1 && [[ "${LMM_AUTO_BUILD_RUNTIME:-}" != "1" && "${LMM_AUTO_BUILD_RUNTIME:-}" != "true" && "${LMM_AUTO_BUILD_RUNTIME:-}" != "yes" ]]; then
            printf 'post-install: CUDA host detected but nvcc not in PATH; skipping GPU build\n'
            printf 'note: set LMM_AUTO_BUILD_RUNTIME=1 to force, or run manually after installing CUDA toolkit\n'
            primary_backend="cpu"
            printf 'post-install: falling back to CPU-only runtime\n'
        elif [[ "$primary_backend" == "cuda" ]] && ! command -v nvcc >/dev/null 2>&1; then
            printf 'post-install: CUDA host detected but nvcc not in PATH; LMM_AUTO_BUILD_RUNTIME is set, so attempting CUDA toolkit install\n'
        elif [[ "$primary_backend" == "vulkan" ]] && ! command -v glslc >/dev/null 2>&1 && ! command -v glslangValidator >/dev/null 2>&1; then
            printf 'post-install: Vulkan host detected but SDK tools not in PATH; skipping GPU build\n'
            printf 'note: set LMM_AUTO_BUILD_RUNTIME=1 to force, or run manually after installing Vulkan SDK\n'
            primary_backend="cpu"
            printf 'post-install: falling back to CPU-only runtime\n'
        else
            printf 'post-install: non-interactive install with %s build tools available; building %s runtime\n' "$primary_backend" "$primary_backend"
        fi
    fi

    # Force the build to write into the installed app share, not the source
    # checkout.  Without this, build-runtime resolves APP_ROOT to the repo
    # directory (because web/ exists there) and writes binaries to the wrong
    # location.
    LLAMA_SERVER_RUNTIME_DIR="${APP_SHARE_DIR}/runtime" \
    LLAMA_AUTO_INSTALL_DEPS=1 \
        "$bin" build-runtime --backend "$primary_backend" 2>&1 || true

    # Post-build validation: ldd + --version checks
    local runtime_dir="${APP_SHARE_DIR}/runtime/llama-server"
    local mark_runtime_invalid=0
    local -a runtime_binaries=()
    local -a valid_runtime_binaries=()
    local b=""
    local payload_binary=""

    if [[ -d "$runtime_dir" ]] && find "$runtime_dir" -name 'llama-server' -type f -print -quit 2>/dev/null | grep -q .; then
        for b in "$runtime_dir"/*-"${primary_backend}"/llama-server; do
            [[ -x "$b" ]] || continue
            runtime_binaries+=("$b")
            break
        done
        while IFS= read -r -d '' b; do
            if ((${#runtime_binaries[@]} > 0)) && [[ "$b" == "${runtime_binaries[0]}" ]]; then
                continue
            fi
            runtime_binaries+=("$b")
        done < <(find "$runtime_dir" -name 'llama-server' -type f -print0 | sort -z)

        for b in "${runtime_binaries[@]}"; do
            payload_binary="${b}.bin"
            if [[ -x "$payload_binary" ]]; then
                missing="$(ldd "$payload_binary" 2>&1 | grep 'not found' | grep -E 'lib(ggml|llama|mtmd)' || true)"
                if [[ -n "$missing" ]]; then
                    printf 'post-install: runtime bundle %s has missing libs: %s\n' "$b" "$missing"
                    continue
                fi
            fi

            if "$b" --version >/dev/null 2>&1; then
                valid_runtime_binaries+=("$b")
            else
                printf 'post-install: runtime bundle failed --version check: %s\n' "$b"
            fi
        done

        if ((${#valid_runtime_binaries[@]} == 0)); then
            printf 'post-install: no built runtime bundle passed validation\n'
            mark_runtime_invalid=1
        fi

        # Backend check: verify binary reports expected backend
        if [[ "$mark_runtime_invalid" -eq 0 ]]; then
            # The build-runtime --backend flag should produce the correct backend
            # This is also checked by validate_runtime_profile() at runtime
            printf 'post-install: runtime build completed and validated successfully\n'
        fi

        # List produced binaries
        find "$runtime_dir" -name 'llama-server' -type f | while read -r b; do
            printf '  -> %s\n' "$b"
        done

        # Persist only if validation passed
        if [[ "$mark_runtime_invalid" -eq 0 ]]; then
            local persisted="no"
            for b in "${valid_runtime_binaries[@]}"; do
                if "$bin" persist-runtime "$b" 2>/dev/null; then
                    persisted="yes"
                    break
                fi
            done
            if [[ "$persisted" == "yes" ]]; then
                printf 'post-install: persisted LLAMA_SERVER_BIN to defaults.env\n'
            else
                printf 'post-install: valid runtime bundles were built but none could be persisted\n' >&2
            fi
        else
            printf 'post-install: runtime build validation failed, not persisting LLAMA_SERVER_BIN\n'
            printf 'post-install: run "%s build-runtime --backend auto" manually after fixing issues\n' "$bin"
        fi
    else
        printf 'post-install: runtime build did not produce a binary\n'
        printf 'post-install: run "%s build-runtime --backend auto" manually to retry\n' "$bin"
    fi
}

# safe_install — portable replacement for `install -m` (GNU coreutils).
# Uses `install` if available and working, otherwise falls back to cp + chmod.
# This handles minimal environments (Alpine, stripped containers) where
# `install` may be missing or broken.
safe_install() {
    local mode="$1"
    local src="$2"
    local dest="$3"

    # Guard: source must exist
    if [[ ! -e "$src" ]]; then
        printf 'warning: source file not found: %s (skipping)\n' "$src" >&2
        return 1
    fi

    # Try native install first (preferred)
    if command -v install >/dev/null 2>&1; then
        if install -m "$mode" "$src" "$dest" 2>/dev/null; then
            return 0
        fi
    fi

    # Fallback: cp + chmod
    if cp "$src" "$dest" 2>/dev/null; then
        chmod "$mode" "$dest" 2>/dev/null
        return 0
    fi

    printf 'error: failed to install %s -> %s\n' "$src" "$dest" >&2
    return 1
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
    for key in LLAMA_MODEL_HARNESS_MODE LLAMA_MODEL_GATEWAY_HOST LLAMA_MODEL_GATEWAY_PORT LLAMA_MODEL_GATEWAY_LOG LLAMA_MODEL_GATEWAY_FAST_ENABLED LLAMA_MODEL_GATEWAY_FAST_PORT LLAMA_MODEL_GATEWAY_FAST_LOG LMM_GATEWAY_FAST_CONTEXT_TIMEOUT_MS LMM_GATEWAY_FAST_CONTEXT_STREAM_TIMEOUT_MS; do
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
    if ! defaults_has_key LLAMA_MODEL_GATEWAY_FAST_ENABLED "$tmp"; then
        printf 'LLAMA_MODEL_GATEWAY_FAST_ENABLED=0\n' >>"$tmp"
    fi
    if ! defaults_has_key LLAMA_MODEL_GATEWAY_FAST_PORT "$tmp"; then
        printf 'LLAMA_MODEL_GATEWAY_FAST_PORT=4011\n' >>"$tmp"
    fi
    if ! defaults_has_key LLAMA_MODEL_GATEWAY_FAST_LOG "$tmp"; then
        printf 'LLAMA_MODEL_GATEWAY_FAST_LOG=$HOME/models/lmm-gateway-fast.log\n' >>"$tmp"
    fi
    if ! defaults_has_key LMM_GATEWAY_FAST_CONTEXT_TIMEOUT_MS "$tmp"; then
        printf 'LMM_GATEWAY_FAST_CONTEXT_TIMEOUT_MS=500\n' >>"$tmp"
    fi
    if ! defaults_has_key LMM_GATEWAY_FAST_CONTEXT_STREAM_TIMEOUT_MS "$tmp"; then
        printf 'LMM_GATEWAY_FAST_CONTEXT_STREAM_TIMEOUT_MS=250\n' >>"$tmp"
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

# Step 1: Build bundled llama.cpp runtime for the host.  This replaces the old
# "no runtime shipped" gap — we now compile GPU/CPU binaries during install so
# fresh installs can actually run models on their hardware.
build_runtime_during_install
install_basedpyright_during_install

# Step 2: Copy any pre-built runtime bundles from the source tree (rare: only
# if the developer built them locally before packaging).  The install build
# from Step 1 already wrote to $APP_SHARE_DIR/runtime, so this only layers
# on extras that aren't host-matched.
if [[ -d "$ROOT_DIR/runtime" ]]; then
    rm -rf "$APP_SHARE_DIR/runtime"
    cp -a "$ROOT_DIR/runtime" "$APP_SHARE_DIR/runtime"
fi
mkdir -p "$APP_SHARE_DIR/branding"
if [[ -f "$ROOT_DIR/desktop/llama-model-manager-icon.svg" ]]; then
    safe_install 0644 "$ROOT_DIR/desktop/llama-model-manager-icon.svg" \
        "$APP_SHARE_DIR/branding/llama-model-manager-icon.svg"
else
    printf 'warning: branding icon not found, skipping\n' >&2
fi

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
interactive_harness_setup_wizard

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

# Conditional runtime retry — only prompt if the earlier build attempt
# (build_runtime_during_install) did not produce a usable binary.
# This catches cases where deps were missing or the build failed silently.
if [[ -t 0 && -t 1 ]]; then
    runtime_dir="${APP_SHARE_DIR}/runtime/llama-server"
    has_runtime="no"
    if [[ -d "$runtime_dir" ]] && find "$runtime_dir" -name 'llama-server' -type f -print -quit 2>/dev/null | grep -q .; then
        has_runtime="yes"
    fi
    if [[ "$has_runtime" != "yes" ]]; then
        printf '\nNo llama.cpp runtime was built during install. Compile one now? [Y/n] '
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
fi
