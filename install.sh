#!/usr/bin/env bash
# Minimum bash version: 4.0+ for pipefail and lowercase expansion.
# macOS users: brew install bash
if (( ${BASH_VERSINFO[0]} < 4 )); then
    printf 'error: bash 4.0 or newer is required (current: %s)\n' "$BASH_VERSION" >&2
    printf '  On macOS: install with: brew install bash\n' >&2
    exit 1
fi
set -euo pipefail

# Portable lowercase helper — avoids bash 4+ ${var,,} syntax
to_lower() {
    printf '%s\n' "$1" | tr '[:upper:]' '[:lower:]'
}

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
    reply="$(to_lower "$reply")"
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

opencode_install_command_available() {
    local command_text="$1"
    case "$command_text" in
        "curl -fsSL https://opencode.ai/install | bash")
            command -v curl >/dev/null 2>&1 && command -v bash >/dev/null 2>&1
            ;;
        "brew install anomalyco/tap/opencode")
            command -v brew >/dev/null 2>&1
            ;;
        "bun add -g opencode-ai")
            command -v bun >/dev/null 2>&1
            ;;
        "npm i -g opencode-ai")
            command -v npm >/dev/null 2>&1
            ;;
        "paru -S opencode")
            command -v paru >/dev/null 2>&1
            ;;
        *)
            return 1
            ;;
    esac
}

prompt_opencode_install_choice() {
    local choice=""
    local command_text=""
    local missing_tool=""

    while true; do
        printf 'How would you like to install OpenCode?\n' >&2
        printf '  1) curl -fsSL https://opencode.ai/install | bash  (recommended)\n' >&2
        printf '  2) brew install anomalyco/tap/opencode             (macOS)\n' >&2
        printf '  3) bun add -g opencode-ai\n' >&2
        printf '  4) npm i -g opencode-ai\n' >&2
        printf '  5) paru -S opencode                               (Arch)\n' >&2
        printf '  s) skip OpenCode installation\n' >&2
        printf 'Choice [1-5, s]: ' >&2

        read -r choice || choice=""
        choice="$(to_lower "$choice")"

        case "$choice" in
            ""|1)
                command_text="curl -fsSL https://opencode.ai/install | bash"
                missing_tool="curl and bash"
                ;;
            2)
                command_text="brew install anomalyco/tap/opencode"
                missing_tool="brew"
                ;;
            3)
                command_text="bun add -g opencode-ai"
                missing_tool="bun"
                ;;
            4)
                command_text="npm i -g opencode-ai"
                missing_tool="npm"
                ;;
            5)
                command_text="paru -S opencode"
                missing_tool="paru"
                ;;
            s|skip|n|no)
                return 0
                ;;
            *)
                printf 'post-install: invalid OpenCode install choice: %s\n' "$choice" >&2
                continue
                ;;
        esac

        if opencode_install_command_available "$command_text"; then
            printf '%s\n' "$command_text"
            return 0
        fi

        printf 'post-install warning: selected OpenCode install method requires %s, but it is not on PATH.\n' "$missing_tool" >&2
        printf 'post-install: choose another OpenCode install method or skip.\n' >&2
    done
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
        printf 'npm exec oh-my-openagent install\n'
    else
        printf ''
    fi
}

install_bun_for_oh_my_openagent_if_needed() {
    if command -v bunx >/dev/null 2>&1 || command -v bun >/dev/null 2>&1; then
        return 0
    fi

    if ! command -v curl >/dev/null 2>&1 || ! command -v bash >/dev/null 2>&1; then
        printf 'post-install: Bun install skipped; curl and bash are required for the Bun installer\n' >&2
        return 1
    fi

    case "${LMM_INSTALL_BUN:-}" in
        1|true|yes|Y|y)
            ;;
        *)
            if [[ -t 0 && -t 1 ]]; then
                local reply=""
                printf 'post-install: Bun is recommended for oh-my-openagent installation but is not on PATH.\n'
                printf 'Install Bun now with: curl -fsSL https://bun.sh/install | bash ? [Y/n] '
                read -r reply || reply=""
                reply="$(to_lower "$reply")"
                if [[ "$reply" == "n" || "$reply" == "no" ]]; then
                    return 1
                fi
            else
                return 1
            fi
            ;;
    esac

    if curl -fsSL https://bun.sh/install | bash; then
        if [[ -d "$HOME/.bun/bin" ]]; then
            case ":$PATH:" in
                *":$HOME/.bun/bin:"*) ;;
                *) export PATH="$HOME/.bun/bin:$PATH" ;;
            esac
            hash -r 2>/dev/null || true
        fi
        printf 'post-install: Bun installer completed\n'
        return 0
    fi

    printf 'post-install warning: Bun installer failed; oh-my-openagent may need npx/npm fallback\n' >&2
    return 1
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
        "npm exec oh-my-openagent install")
            if command -v npm >/dev/null 2>&1; then
                npm exec oh-my-openagent install
            else
                printf 'post-install: npm is unavailable\n' >&2
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
        printf 'post-install: opencode already available: %s\n' "$(command -v opencode)"
        printf 'Skip OpenCode install/configuration step? [Y/n] '
        read -r reply || reply=""
        reply="$(to_lower "$reply")"
        if [[ "$reply" != "n" && "$reply" != "no" ]]; then
            recommendation=""
        else
            recommendation="$(prompt_opencode_install_choice)"
        fi
    fi

    if ! command -v opencode >/dev/null 2>&1; then
        printf 'post-install: opencode is not installed or not on PATH\n'
        recommendation="$(prompt_opencode_install_choice)"
    fi

    if [[ -n "$recommendation" ]]; then
        if run_opencode_install_command "$recommendation"; then
            printf 'post-install: OpenCode install command completed\n'
        else
            printf 'post-install warning: OpenCode install command failed; retry manually with: %s\n' "$recommendation" >&2
        fi
    else
        printf 'post-install: OpenCode install skipped\n'
    fi

    if [[ -f "$openagent_config" ]]; then
        printf 'post-install: oh-my-openagent config found: %s\n' "$openagent_config"
        printf 'Skip oh-my-openagent install/sync step? [Y/n] '
        read -r reply || reply=""
        reply="$(to_lower "$reply")"
        if [[ "$reply" != "n" && "$reply" != "no" ]]; then
            return 0
        fi
    fi

    if [[ ! -f "$openagent_config" || "$reply" == "n" || "$reply" == "no" ]]; then
        if [[ -f "$openagent_config" ]]; then
            printf 'post-install: running oh-my-openagent repair/sync flow for existing config: %s\n' "$openagent_config"
        else
            printf 'post-install: oh-my-openagent config missing: %s\n' "$openagent_config"
        fi
        printf 'Fetch the oh-my-openagent installation guide now? [Y/n] '
        read -r reply || reply=""
        reply="$(to_lower "$reply")"
        if [[ "$reply" != "n" && "$reply" != "no" ]]; then
            fetch_oh_my_openagent_guide "$guide_url" "$guide_path" || true
        fi

        install_bun_for_oh_my_openagent_if_needed || true
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
        printf 'Install oh-my-openagent (enables background subagents, task() delegation, model fallback)? [Y/n] '
        read -r reply || reply=""
        reply="$(to_lower "$reply")"
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

# CUDA architecture and toolkit setup for llama.cpp / GGML.
#
# Goals:
#   - Detect NVIDIA GPU compute capability with nvidia-smi.
#   - Export GGML_CUDA_ARCHITECTURES for llama.cpp/CMake.
#   - Prefer a compatible CUDA toolkit lane for the detected GPU.
#   - Avoid CUDA 13.1 on non-Blackwell GPUs when CUDA 12.9 is available,
#     because CUDA 13.1 can hit glibc rsqrt/rsqrtf noexcept header conflicts.
#   - Select gcc/g++ 13 or 14 as nvcc host compiler when available.
#   - Fall back to CPU cleanly if CUDA cannot be made buildable.

run_root_cmd() {
    if [[ "$EUID" -eq 0 ]]; then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        printf 'post-install warning: sudo unavailable; cannot run privileged command: %s\n' "$*" >&2
        return 1
    fi
}

apt_package_available() {
    local pkg="$1"
    command -v apt-cache >/dev/null 2>&1 || return 1

    apt-cache show "$pkg" >/dev/null 2>&1 && return 0

    apt-cache policy "$pkg" 2>/dev/null \
        | awk '
            $1 == "Candidate:" && $2 != "(none)" { found = 1 }
            END { exit found ? 0 : 1 }
        '
}

install_apt_packages_best_effort() {
    command -v apt-get >/dev/null 2>&1 || return 1

    if ! run_root_cmd apt-get update -qq; then
        printf 'post-install warning: apt-get update failed; dependency installation may be incomplete\n' >&2
        return 1
    fi

    local pkg
    local available=()
    for pkg in "$@"; do
        if apt_package_available "$pkg"; then
            available+=("$pkg")
        else
            printf 'post-install warning: package unavailable on this system: %s\n' "$pkg" >&2
        fi
    done

    if ((${#available[@]} == 0)); then
        return 0
    fi

    run_root_cmd apt-get install -y -qq "${available[@]}" || {
        printf 'post-install warning: apt failed to install one or more packages: %s\n' "${available[*]}" >&2
        return 1
    }
}

detect_cuda_deb_repo_slug() {
    local os_release="${CUDA_OS_RELEASE_FILE:-/etc/os-release}"
    local os_id=""
    local version_id=""
    local version_major=""
    local ubuntu_codename=""

    [[ -r "$os_release" ]] || return 1

    # shellcheck disable=SC1090
    . "$os_release"

    os_id="${ID:-}"
    version_id="${VERSION_ID:-}"
    version_major="${version_id%%.*}"
    ubuntu_codename="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"

    case "${os_id}:${version_id}" in
        ubuntu:26.04) printf 'ubuntu2604\n' ;;
        ubuntu:24.04) printf 'ubuntu2404\n' ;;
        ubuntu:22.04) printf 'ubuntu2204\n' ;;
        ubuntu:20.04) printf 'ubuntu2004\n' ;;
        debian:13)    printf 'debian13\n' ;;
        debian:12)    printf 'debian12\n' ;;
        debian:11)    printf 'debian11\n' ;;
        *)
            case "$ubuntu_codename" in
                resolute) printf 'ubuntu2604\n' ;;
                noble)    printf 'ubuntu2404\n' ;;
                jammy)    printf 'ubuntu2204\n' ;;
                focal)    printf 'ubuntu2004\n' ;;
                trixie)   printf 'debian13\n' ;;
                bookworm) printf 'debian12\n' ;;
                bullseye) printf 'debian11\n' ;;
                *)
                    case "${os_id}:${version_major}" in
                        ubuntu:26) printf 'ubuntu2604\n' ;;
                        ubuntu:24) printf 'ubuntu2404\n' ;;
                        ubuntu:22) printf 'ubuntu2204\n' ;;
                        ubuntu:20) printf 'ubuntu2004\n' ;;
                        debian:13) printf 'debian13\n' ;;
                        debian:12) printf 'debian12\n' ;;
                        debian:11) printf 'debian11\n' ;;
                        *) return 1 ;;
                    esac
                    ;;
            esac
            ;;
    esac
}

detect_cuda_deb_repo_arch() {
    local deb_arch=""

    command -v dpkg >/dev/null 2>&1 || return 1
    deb_arch="$(dpkg --print-architecture 2>/dev/null || true)"

    case "$deb_arch" in
        amd64) printf 'x86_64\n' ;;
        arm64) printf 'sbsa\n' ;;
        *) return 1 ;;
    esac
}

is_ubuntu_2604_or_newer() {
    local os_release="${CUDA_OS_RELEASE_FILE:-/etc/os-release}"
    local os_id=""
    local version_id=""
    local version_major=""
    local ubuntu_codename=""

    [[ -r "$os_release" ]] || return 1

    # shellcheck disable=SC1090
    . "$os_release"

    os_id="${ID:-}"
    version_id="${VERSION_ID:-}"
    version_major="${version_id%%.*}"
    ubuntu_codename="${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}"

    [[ "$os_id" == "ubuntu" ]] || return 1

    case "$ubuntu_codename" in
        resolute) return 0 ;;
    esac

    [[ "$version_major" =~ ^[0-9]+$ ]] || return 1
    ((version_major >= 26))
}

enable_ubuntu_multiverse_best_effort() {
    command -v apt-get >/dev/null 2>&1 || return 0

    if command -v add-apt-repository >/dev/null 2>&1; then
        run_root_cmd add-apt-repository -y multiverse || true
        run_root_cmd apt-get update -qq || true
        return 0
    fi

    install_apt_packages_best_effort software-properties-common

    if command -v add-apt-repository >/dev/null 2>&1; then
        run_root_cmd add-apt-repository -y multiverse || true
        run_root_cmd apt-get update -qq || true
    else
        printf 'post-install warning: add-apt-repository unavailable; cannot automatically enable Ubuntu multiverse\n' >&2
    fi
}

cuda_repo_slug_fallbacks() {
    local primary="$1"

    case "$primary" in
        ubuntu2604) printf 'ubuntu2604 ubuntu2404\n' ;;
        debian13)   printf 'debian13 debian12\n' ;;
        *)          printf '%s\n' "$primary" ;;
    esac
}

cuda_toolkit_package_candidate_visible() {
    local pkg=""

    command -v apt-cache >/dev/null 2>&1 || return 1

    for pkg in \
        cuda-toolkit-13-1 \
        cuda-nvcc-13-1 \
        cuda-toolkit-12-9 \
        cuda-nvcc-12-9 \
        cuda-toolkit-12-8 \
        cuda-nvcc-12-8 \
        cuda-toolkit \
        cuda-nvcc \
        cuda-compiler \
        libcublas-dev
    do
        if apt_package_available "$pkg"; then
            return 0
        fi
    done

    return 1
}

bootstrap_nvidia_cuda_apt_repo_for_slug() {
    local repo_slug="$1"
    local repo_arch="$2"
    local keyring_deb="cuda-keyring_1.1-1_all.deb"
    local keyring_url="https://developer.download.nvidia.com/compute/cuda/repos/${repo_slug}/${repo_arch}/${keyring_deb}"
    local tmp_deb=""

    tmp_deb="$(mktemp "${TMPDIR:-/tmp}/cuda-keyring.XXXXXX.deb")"

    printf 'post-install: bootstrapping NVIDIA CUDA apt repo: %s/%s\n' "$repo_slug" "$repo_arch"

    if command -v curl >/dev/null 2>&1; then
        if ! curl -fsSL "$keyring_url" -o "$tmp_deb"; then
            printf 'post-install warning: failed to download CUDA keyring: %s\n' "$keyring_url" >&2
            rm -f "$tmp_deb"
            return 1
        fi
    elif command -v wget >/dev/null 2>&1; then
        if ! wget -qO "$tmp_deb" "$keyring_url"; then
            printf 'post-install warning: failed to download CUDA keyring: %s\n' "$keyring_url" >&2
            rm -f "$tmp_deb"
            return 1
        fi
    else
        printf 'post-install warning: curl/wget unavailable; cannot download CUDA keyring\n' >&2
        rm -f "$tmp_deb"
        return 1
    fi

    if ! run_root_cmd dpkg -i "$tmp_deb"; then
        printf 'post-install warning: failed to install CUDA keyring package from %s/%s\n' "$repo_slug" "$repo_arch" >&2
        rm -f "$tmp_deb"
        return 1
    fi

    rm -f "$tmp_deb"

    if ! run_root_cmd apt-get update -qq; then
        printf 'post-install warning: apt-get update failed after CUDA repo bootstrap for %s/%s\n' "$repo_slug" "$repo_arch" >&2
        return 1
    fi

    return 0
}

bootstrap_nvidia_cuda_apt_repo() {
    [[ "${primary_backend:-}" == "cuda" ]] || return 0
    command -v apt-get >/dev/null 2>&1 || return 0
    command -v dpkg >/dev/null 2>&1 || {
        printf 'post-install warning: dpkg unavailable; cannot install NVIDIA CUDA apt keyring package\n' >&2
        return 0
    }

    local primary_slug=""
    local repo_slugs=""
    local repo_slug=""
    local repo_arch=""

    primary_slug="$(detect_cuda_deb_repo_slug || true)"
    if [[ -z "$primary_slug" ]]; then
        printf 'post-install warning: unsupported Debian/Ubuntu release for automatic NVIDIA CUDA apt repo setup\n' >&2
        printf 'post-install warning: skipping CUDA apt repo bootstrap; existing apt sources will be used\n' >&2
        return 0
    fi

    repo_arch="$(detect_cuda_deb_repo_arch || true)"
    if [[ -z "$repo_arch" ]]; then
        printf 'post-install warning: unsupported architecture for NVIDIA CUDA apt repo: %s\n' "$(dpkg --print-architecture 2>/dev/null || true)" >&2
        return 0
    fi

    repo_slugs="$(cuda_repo_slug_fallbacks "$primary_slug")"

    if dpkg -s cuda-keyring >/dev/null 2>&1; then
        printf 'post-install: NVIDIA CUDA apt keyring already installed; refreshing apt cache\n'
        run_root_cmd apt-get update -qq || {
            printf 'post-install warning: apt-get update failed after existing CUDA keyring check\n' >&2
        }
        if cuda_toolkit_package_candidate_visible; then
            return 0
        fi
        printf 'post-install warning: CUDA apt keyring exists, but no CUDA toolkit package candidates are visible; trying compatibility repo fallback\n' >&2
    fi

    for repo_slug in $repo_slugs; do
        if [[ "$repo_slug" != "$primary_slug" ]]; then
            case "$primary_slug:$repo_slug" in
                ubuntu2604:ubuntu2404)
                    printf 'post-install warning: Ubuntu 26.04 native CUDA repo did not expose toolkit packages; trying NVIDIA ubuntu2404 compatibility repo.\n' >&2
                    ;;
                debian13:debian12)
                    printf 'post-install warning: Debian 13 native CUDA repo did not expose toolkit packages; trying NVIDIA debian12 compatibility repo.\n' >&2
                    ;;
            esac
        fi

        if ! bootstrap_nvidia_cuda_apt_repo_for_slug "$repo_slug" "$repo_arch"; then
            continue
        fi

        if cuda_toolkit_package_candidate_visible; then
            printf 'post-install: NVIDIA CUDA apt repo ready via %s/%s\n' "$repo_slug" "$repo_arch"
            return 0
        fi

        printf 'post-install warning: NVIDIA CUDA apt repo %s/%s did not expose CUDA toolkit package candidates\n' "$repo_slug" "$repo_arch" >&2
    done

    printf 'post-install warning: failed to bootstrap a NVIDIA CUDA apt repo with visible toolkit packages: %s\n' "$repo_slugs" >&2
}

warn_cuda_apt_visibility_if_nvcc_missing() {
    [[ "${primary_backend:-}" == "cuda" ]] || return 0
    command -v nvcc >/dev/null 2>&1 && return 0
    command -v apt-cache >/dev/null 2>&1 || return 0

    printf 'post-install warning: nvcc is still unavailable. Your apt sources may not expose NVIDIA CUDA toolkit packages.\n' >&2
    printf 'post-install warning: check with: apt-cache policy cuda-toolkit-12-9 cuda-nvcc-12-9 cuda-toolkit-12-8 cuda-nvcc-12-8 cuda-toolkit cuda-nvcc cuda-compiler libcublas-dev\n' >&2
    printf 'post-install warning: CPU runtime fallback will be used unless CUDA toolkit is installed manually.\n' >&2
}

detect_cuda_architectures() {
    local caps=""
    local cap=""
    local arch=""
    local arches=()
    local unique_arches=""

    if ! command -v nvidia-smi >/dev/null 2>&1; then
        printf ''
        return 1
    fi

    caps="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null || true)"
    [[ -n "$caps" ]] || {
        printf ''
        return 1
    }

    while IFS= read -r cap; do
        cap="$(printf '%s' "$cap" | tr -d '[:space:]')"
        [[ -n "$cap" ]] || continue

        case "$cap" in
            # Maxwell
            5.0|50)   arch="50" ;;
            5.2|52)   arch="52" ;;
            5.3|53)   arch="53" ;;

            # Pascal
            6.0|60)   arch="60" ;;
            6.1|61)   arch="61" ;;
            6.2|62)   arch="62" ;;

            # Volta / Xavier
            7.0|70)   arch="70" ;;
            7.2|72)   arch="72" ;;

            # Turing
            7.5|75)   arch="75" ;;

            # Ampere
            8.0|80)   arch="80" ;;
            8.6|86)   arch="86" ;;
            8.7|87)   arch="87" ;;

            # Ada Lovelace
            8.9|89)   arch="89" ;;

            # Hopper
            9.0|90)   arch="90" ;;

            # Blackwell / future reported capabilities
            10.0|100) arch="100" ;;
            10.1|101) arch="101" ;;
            12.0|120) arch="120" ;;

            *)
                printf 'post-install warning: unrecognised CUDA compute capability: %s\n' "$cap" >&2
                continue
                ;;
        esac

        case " $unique_arches " in
            *" $arch "*) ;;
            *)
                unique_arches="${unique_arches:+$unique_arches }$arch"
                arches+=("$arch")
                ;;
        esac
    done <<< "$caps"

    if ((${#arches[@]} == 0)); then
        printf ''
        return 1
    fi

    local IFS=';'
    printf '%s\n' "${arches[*]}"
}

cuda_arches_need_legacy_toolkit() {
    local cuda_arches="${1:-}"
    local arch=""

    [[ -n "$cuda_arches" ]] || cuda_arches="${GGML_CUDA_ARCHITECTURES:-}"
    [[ -n "$cuda_arches" ]] || cuda_arches="$(detect_cuda_architectures || true)"
    [[ -n "$cuda_arches" ]] || return 1

    IFS=';' read -r -a _cuda_arch_array <<< "$cuda_arches"
    for arch in "${_cuda_arch_array[@]}"; do
        case "$arch" in
            50|52|53|60|61|62|70|72)
                return 0
                ;;
        esac
    done

    return 1
}

cuda_arches_need_modern_toolkit() {
    local cuda_arches="${1:-}"
    local arch=""

    [[ -n "$cuda_arches" ]] || cuda_arches="${GGML_CUDA_ARCHITECTURES:-}"
    [[ -n "$cuda_arches" ]] || cuda_arches="$(detect_cuda_architectures || true)"
    [[ -n "$cuda_arches" ]] || return 1

    IFS=';' read -r -a _cuda_arch_array <<< "$cuda_arches"
    for arch in "${_cuda_arch_array[@]}"; do
        case "$arch" in
            100|101|120)
                return 0
                ;;
        esac
    done

    return 1
}

legacy_cuda_toolkit_paths() {
    if [[ -n "${LMM_LEGACY_CUDA_PATHS:-}" ]]; then
        printf '%s\n' "$LMM_LEGACY_CUDA_PATHS"
    elif [[ -n "${LMM_LEGACY_CUDA_TOOLKIT_PATH:-}" ]]; then
        printf '%s\n' "$LMM_LEGACY_CUDA_TOOLKIT_PATH"
    else
        printf '/usr/local/cuda-11.8 /opt/cuda-11.8\n'
    fi
}

legacy_cuda_runfile_url() {
    printf '%s\n' "https://developer.download.nvidia.com/compute/cuda/11.8.0/local_installers/cuda_11.8.0_520.61.05_linux.run"
}

legacy_cuda_runfile_name() {
    printf '%s\n' "cuda_11.8.0_520.61.05_linux.run"
}

legacy_cuda_toolkit_path() {
    printf '%s\n' "${LMM_LEGACY_CUDA_TOOLKIT_PATH:-/usr/local/cuda-11.8}"
}

append_cmake_toolkit_root_arg() {
    local cuda_path="$1"
    export CMAKE_ARGS="$(printf '%s\n' "${CMAKE_ARGS:-}" | sed -E 's/(^|[[:space:]])-DCUDAToolkit_ROOT=[^[:space:]]+//g' | xargs)"
    export CMAKE_ARGS="${CMAKE_ARGS:-} -DCUDAToolkit_ROOT=${cuda_path}"
    export LMM_CMAKE_ARGS="$(printf '%s\n' "${LMM_CMAKE_ARGS:-}" | sed -E 's/(^|[[:space:]])-DCUDAToolkit_ROOT=[^[:space:]]+//g' | xargs)"
    export LMM_CMAKE_ARGS="${LMM_CMAKE_ARGS:-} -DCUDAToolkit_ROOT=${cuda_path}"
}

configure_legacy_cuda_host_compiler() {
    [[ "${primary_backend:-}" == "cuda" ]] || return 0
    cuda_arches_need_legacy_toolkit || return 0

    if { [[ ! -x /usr/bin/gcc-11 ]] || [[ ! -x /usr/bin/g++-11 ]]; } &&
        [[ "${LMM_SKIP_LEGACY_CUDA_COMPILER_INSTALL:-}" != "1" ]] &&
        command -v apt-get >/dev/null 2>&1; then
        install_apt_packages_best_effort gcc-11 g++-11
    fi

    if [[ -x /usr/bin/gcc-11 && -x /usr/bin/g++-11 ]]; then
        export CC=/usr/bin/gcc-11
        export CXX=/usr/bin/g++-11
        export CUDAHOSTCXX=/usr/bin/g++-11
        printf 'post-install: selected gcc/g++ 11 for legacy CUDA 11.8 host compiler\n'
    else
        printf 'post-install warning: gcc-11/g++-11 unavailable; CUDA 11.8 may reject the default host compiler\n' >&2
    fi
}

legacy_cuda_header_patch_diagnostic() {
    local cuda_path="$1"
    local header_h="$cuda_path/include/crt/math_functions.h"
    local header_hpp="$cuda_path/include/crt/math_functions.hpp"

    is_ubuntu_2604_or_newer || return 0
    [[ -e "$header_h" || -e "$header_hpp" ]] || return 0

    printf 'post-install warning: Legacy CUDA 11.8 on Ubuntu 26.04 may require local noexcept(true) patches in:\n' >&2
    printf '  %s\n' "$header_h" >&2
    printf '  %s\n' "$header_hpp" >&2
    printf 'post-install warning: observed conflicting functions: cospi sinpi rsqrt cospif sinpif rsqrtf\n' >&2
    if [[ "${LMM_ALLOW_CUDA_VENDOR_HEADER_PATCH:-}" == "1" ]]; then
        printf 'post-install warning: LMM_ALLOW_CUDA_VENDOR_HEADER_PATCH=1 was set, but automatic vendor header patching is not implemented; patch manually and rerun if CUDA compile fails.\n' >&2
    else
        printf 'post-install warning: not patching NVIDIA vendor headers automatically; set LMM_ALLOW_CUDA_VENDOR_HEADER_PATCH=1 only after reviewing the local patch.\n' >&2
    fi
}

normalize_legacy_cuda_cublas_layout() {
    local cuda_path="${1:-/usr/local/cuda-11.8}"
    local cublas_root="$cuda_path/libcublas/targets/x86_64-linux"
    local lib=""
    local header=""

    [[ -d "$cublas_root" ]] || return 0

    run_root_cmd mkdir -p "$cuda_path/lib64" "$cuda_path/lib64/stubs" "$cuda_path/include" || return 0

    for lib in \
        libcublas.so \
        libcublas.so.11 \
        libcublasLt.so \
        libcublasLt.so.11 \
        libcublas_static.a \
        libcublasLt_static.a; do
        [[ -e "$cublas_root/lib/$lib" ]] && run_root_cmd ln -sf "$cublas_root/lib/$lib" "$cuda_path/lib64/$lib" || true
    done

    for lib in libcublas.so libcublasLt.so; do
        [[ -e "$cublas_root/lib/stubs/$lib" ]] && run_root_cmd ln -sf "$cublas_root/lib/stubs/$lib" "$cuda_path/lib64/stubs/$lib" || true
    done

    for header in cublas.h cublasLt.h cublasXt.h cublas_api.h cublas_v2.h nvblas.h; do
        [[ -e "$cublas_root/include/$header" ]] && run_root_cmd ln -sf "$cublas_root/include/$header" "$cuda_path/include/$header" || true
    done
}

normalize_legacy_cuda_cccl_layout() {
    local cuda_path="${1:-/usr/local/cuda-11.8}"
    local cccl_root="$cuda_path/cuda_cccl/targets/x86_64-linux/include"
    local dir=""

    [[ -d "$cccl_root" ]] || return 0

    run_root_cmd mkdir -p "$cuda_path/include" || return 0
    for dir in cub thrust cuda nv; do
        [[ -e "$cccl_root/$dir" ]] && run_root_cmd ln -sfn "$cccl_root/$dir" "$cuda_path/include/$dir" || true
    done
}

select_legacy_cuda_11_8_for_build() {
    [[ "${primary_backend:-}" == "cuda" ]] || return 0
    cuda_arches_need_legacy_toolkit || return 1

    local legacy_path=""
    local legacy_paths=""

    legacy_paths="$(legacy_cuda_toolkit_paths)"
    for legacy_path in $legacy_paths; do
        if [[ -x "$legacy_path/bin/nvcc" ]]; then
            printf 'post-install: selecting CUDA 11.8 toolkit for legacy CUDA arch(es): %s\n' "${GGML_CUDA_ARCHITECTURES:-unknown}"
            printf 'post-install: legacy CUDA toolkit path: %s\n' "$legacy_path"

            case ":$PATH:" in
                *":$legacy_path/bin:"*) ;;
                *) export PATH="$legacy_path/bin:$PATH" ;;
            esac

            case ":${LD_LIBRARY_PATH:-}:" in
                *":$legacy_path/lib64:"*) ;;
                *) export LD_LIBRARY_PATH="$legacy_path/lib64:${LD_LIBRARY_PATH:-}" ;;
            esac

            export CUDA_HOME="$legacy_path"
            export CUDA_PATH="$legacy_path"
            export CUDAToolkit_ROOT="$legacy_path"
            append_cmake_toolkit_root_arg "$legacy_path"
            configure_legacy_cuda_host_compiler
            legacy_cuda_header_patch_diagnostic "$legacy_path"
            normalize_legacy_cuda_cublas_layout "$legacy_path"
            normalize_legacy_cuda_cccl_layout "$legacy_path"
            export LMM_LEGACY_CUDA_SELECTED=1
            hash -r 2>/dev/null || true
            "$legacy_path/bin/nvcc" --version || true
            return 0
        fi
    done

    return 1
}

select_legacy_cuda_toolkit_if_present() {
    select_legacy_cuda_11_8_for_build "$@"
}

allow_legacy_cuda_runfile_install() {
    case "${LMM_ALLOW_LEGACY_CUDA_RUNFILE:-}" in
        1|true|yes|Y|y) return 0 ;;
    esac

    if [[ -t 0 && -t 1 ]]; then
        local reply=""
        printf 'post-install: legacy CUDA GPU detected and CUDA 11.8 toolkit is missing.\n'
        printf 'post-install: CUDA 11.8 toolkit-only install can be downloaded from NVIDIA (~4.3 GB).\n'
        printf 'post-install: the installer will run the NVIDIA runfile with --silent --toolkit only; it will not install/replace your NVIDIA driver.\n'
        printf 'Download and install CUDA 11.8 toolkit-only now? [y/N] '
        read -r reply || reply=""
        reply="$(to_lower "$reply")"
        [[ "$reply" == "y" || "$reply" == "yes" ]]
        return $?
    fi

    return 1
}

find_existing_legacy_cuda_runfile() {
    local runfile_name=""
    local candidate=""

    runfile_name="$(legacy_cuda_runfile_name)"
    for candidate in \
        "${XDG_CACHE_HOME:-$HOME/.cache}/llama-model-manager/cuda/${runfile_name}" \
        "$HOME/${runfile_name}" \
        "$HOME/Downloads/${runfile_name}" \
        "/tmp/${runfile_name}"; do
        if [[ -s "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    return 1
}

download_legacy_cuda_runfile() {
    local target_dir="${XDG_CACHE_HOME:-$HOME/.cache}/llama-model-manager/cuda"
    local runfile_name=""
    local runfile_url=""
    local runfile_path=""
    local existing_runfile=""

    runfile_name="$(legacy_cuda_runfile_name)"
    runfile_url="$(legacy_cuda_runfile_url)"
    runfile_path="${target_dir}/${runfile_name}"

    mkdir -p "$target_dir"

    existing_runfile="$(find_existing_legacy_cuda_runfile || true)"
    if [[ -n "$existing_runfile" ]]; then
        if [[ "$existing_runfile" != "$runfile_path" ]]; then
            printf 'post-install: reusing existing CUDA 11.8 runfile: %s\n' "$existing_runfile" >&2
            cp -f "$existing_runfile" "$runfile_path" || {
                printf 'post-install warning: failed to copy existing CUDA 11.8 runfile from %s\n' "$existing_runfile" >&2
                return 1
            }
        fi
        chmod 0755 "$runfile_path" || true
        printf '%s\n' "$runfile_path"
        return 0
    fi

    if [[ -s "$runfile_path" ]]; then
        printf '%s\n' "$runfile_path"
        return 0
    fi

    printf 'post-install: downloading CUDA 11.8 toolkit runfile from NVIDIA:\n' >&2
    printf '  %s\n' "$runfile_url" >&2

    if command -v curl >/dev/null 2>&1; then
        curl -fL --continue-at - "$runfile_url" -o "$runfile_path" || {
            rm -f "$runfile_path"
            return 1
        }
    elif command -v wget >/dev/null 2>&1; then
        wget -c -O "$runfile_path" "$runfile_url" || {
            rm -f "$runfile_path"
            return 1
        }
    else
        printf 'post-install warning: curl/wget unavailable; cannot download CUDA 11.8 runfile\n' >&2
        return 1
    fi

    chmod 0755 "$runfile_path" || true
    printf '%s\n' "$runfile_path"
}

install_legacy_cuda_11_8_toolkit_runfile() {
    [[ "${primary_backend:-}" == "cuda" ]] || return 0
    cuda_arches_need_legacy_toolkit || return 1

    local legacy_path=""
    local runfile_path=""

    legacy_path="$(legacy_cuda_toolkit_path)"

    if [[ -x "$legacy_path/bin/nvcc" ]]; then
        printf 'post-install: CUDA 11.8 already installed at %s\n' "$legacy_path"
        return 0
    fi

    allow_legacy_cuda_runfile_install || {
        printf 'post-install warning: CUDA 11.8 toolkit install not approved; CPU fallback will be used for legacy GPU.\n' >&2
        return 1
    }

    runfile_path="$(download_legacy_cuda_runfile)" || {
        printf 'post-install warning: failed to download CUDA 11.8 runfile; CPU fallback will be used\n' >&2
        return 1
    }

    printf 'post-install: installing CUDA 11.8 toolkit-only from runfile\n'

    if ! run_root_cmd sh "$runfile_path" --silent --toolkit; then
        printf 'post-install warning: CUDA 11.8 toolkit-only runfile install failed\n' >&2
        return 1
    fi

    if [[ ! -x "$legacy_path/bin/nvcc" ]]; then
        printf 'post-install warning: CUDA 11.8 install completed but nvcc was not found at %s/bin/nvcc\n' "$legacy_path" >&2
        return 1
    fi

    printf 'post-install: CUDA 11.8 toolkit installed successfully at %s\n' "$legacy_path"
    return 0
}

configure_legacy_cuda_toolkit_for_build() {
    [[ "${primary_backend:-}" == "cuda" ]] || return 0
    cuda_arches_need_legacy_toolkit || return 0

    if select_legacy_cuda_11_8_for_build; then
        return 0
    fi

    if install_legacy_cuda_11_8_toolkit_runfile; then
        select_legacy_cuda_11_8_for_build
        return $?
    fi

    printf 'post-install warning: legacy CUDA GPU detected: %s\n' "${GGML_CUDA_ARCHITECTURES:-unknown}" >&2
    printf 'post-install warning: legacy CUDA GPU detected but CUDA 11.8 toolkit is unavailable.\n' >&2
    printf 'post-install warning: falling back to CPU runtime.\n' >&2
    printf 'post-install hint: legacy CUDA setup example:\n' >&2
    printf '  install CUDA 11.8 toolkit-only from NVIDIA runfile, then rerun:\n' >&2
    printf '  export PATH=/usr/local/cuda-11.8/bin:$PATH\n' >&2
    printf '  export LD_LIBRARY_PATH=/usr/local/cuda-11.8/lib64:$LD_LIBRARY_PATH\n' >&2
    printf '  export CUDA_HOME=/usr/local/cuda-11.8\n' >&2
    printf '  export CUDA_PATH=/usr/local/cuda-11.8\n' >&2
    printf '  export CUDAToolkit_ROOT=/usr/local/cuda-11.8\n' >&2
    printf '  export GGML_CUDA_ARCHITECTURES=%s\n' "${GGML_CUDA_ARCHITECTURES:-52}" >&2
    printf '  llama-model build-runtime --backend cuda\n' >&2

    primary_backend="cpu"
    unset GGML_CUDA_ARCHITECTURES
    strip_cmake_cuda_args
    return 0
}

guard_unsupported_legacy_cuda_architecture() {
    configure_legacy_cuda_toolkit_for_build "$@"
}

defaults_env_value_for_key() {
    local key="$1"
    local file="$CONFIG_DIR/defaults.env"

    [[ -f "$file" ]] || return 1

    python3 - "$file" "$key" <<'PY'
import shlex
import sys
from pathlib import Path

path = Path(sys.argv[1])
key = sys.argv[2]

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
        if part.startswith(key + "="):
            value = part.split("=", 1)[1]
            if value:
                print(value)
                raise SystemExit(0)

raise SystemExit(1)
PY
}

find_existing_llama_server_binary() {
    local candidate=""
    local saved_bin=""
    local runtime_dir="$APP_SHARE_DIR/runtime/llama-server"

    if [[ -n "${LLAMA_SERVER_BIN:-}" && -x "${LLAMA_SERVER_BIN:-}" ]]; then
        printf '%s\n' "$LLAMA_SERVER_BIN"
        return 0
    fi

    saved_bin="$(defaults_env_value_for_key LLAMA_SERVER_BIN 2>/dev/null || true)"
    if [[ -n "$saved_bin" && -x "$saved_bin" ]]; then
        printf '%s\n' "$saved_bin"
        return 0
    fi

    if [[ -n "${primary_backend:-}" && -d "$runtime_dir" ]]; then
        candidate="$(find "$runtime_dir" -maxdepth 2 -type f -path "*-${primary_backend}/llama-server" -executable -print -quit 2>/dev/null || true)"
        if [[ -n "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    fi

    if [[ -d "$runtime_dir" ]]; then
        candidate="$(find "$runtime_dir" -maxdepth 2 -type f -path "*-cuda/llama-server" -executable -print -quit 2>/dev/null || true)"
        if [[ -n "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi

        candidate="$(find "$runtime_dir" -maxdepth 2 -type f -name llama-server -executable -print -quit 2>/dev/null || true)"
        if [[ -n "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    fi

    candidate="$(command -v llama-server 2>/dev/null || true)"
    if [[ -n "$candidate" && -x "$candidate" ]]; then
        printf '%s\n' "$candidate"
        return 0
    fi

    for candidate in \
        "$HOME/.local/bin/llama-server" \
        "/usr/local/bin/llama-server" \
        "/usr/bin/llama-server" \
        "/opt/llama.cpp/bin/llama-server" \
        "/opt/llama-server/llama-server"; do
        if [[ -x "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    return 1
}

validate_existing_llama_server_binary() {
    local binary="$1"
    [[ -x "$binary" ]] || return 1
    "$binary" --version >/dev/null 2>&1
}

existing_llama_server_backend_hint() {
    local binary="$1"
    local output=""
    local dir=""

    case "$binary" in
        *-cuda/llama-server)   printf 'cuda\n'; return 0 ;;
        *-vulkan/llama-server) printf 'vulkan\n'; return 0 ;;
        *-metal/llama-server)  printf 'metal\n'; return 0 ;;
        *-cpu/llama-server)    printf 'cpu\n'; return 0 ;;
    esac

    dir="$(dirname "$binary")"

    if [[ -e "$dir/libggml-cuda.so" ]] || [[ -e "$dir/libggml-cuda.so.0" ]] || compgen -G "$dir/libggml-cuda.so.*" >/dev/null; then
        printf 'cuda\n'
        return 0
    fi

    if [[ -e "$dir/libggml-vulkan.so" ]] || compgen -G "$dir/libggml-vulkan.so.*" >/dev/null; then
        printf 'vulkan\n'
        return 0
    fi

    output="$("$binary" --version 2>&1 || true)"
    if printf '%s\n' "$output" | grep -qi 'cuda\|cublas\|ggml-cuda'; then
        printf 'cuda\n'
    elif printf '%s\n' "$output" | grep -qi 'vulkan'; then
        printf 'vulkan\n'
    elif printf '%s\n' "$output" | grep -qi 'metal'; then
        printf 'metal\n'
    else
        printf 'unknown\n'
    fi
}

persist_existing_llama_server_binary() {
    local binary="$1"

    mkdir -p "$CONFIG_DIR"
    if [[ ! -f "$CONFIG_DIR/defaults.env" && -f "$ROOT_DIR/config/defaults.env.example" ]]; then
        safe_install 0644 "$ROOT_DIR/config/defaults.env.example" "$CONFIG_DIR/defaults.env"
    elif [[ ! -f "$CONFIG_DIR/defaults.env" ]]; then
        : >"$CONFIG_DIR/defaults.env"
    fi

    if grep -Eq '^[[:space:]]*(export[[:space:]]+)?LLAMA_SERVER_BIN=' "$CONFIG_DIR/defaults.env"; then
        local tmp_defaults=""
        tmp_defaults="$(mktemp)"
        awk -v binary="$binary" '
            /^[[:space:]]*(export[[:space:]]+)?LLAMA_SERVER_BIN=/ {
                print "LLAMA_SERVER_BIN=" binary
                next
            }
            { print }
        ' "$CONFIG_DIR/defaults.env" >"$tmp_defaults"
        mv "$tmp_defaults" "$CONFIG_DIR/defaults.env"
    else
        printf '\nLLAMA_SERVER_BIN=%s\n' "$binary" >>"$CONFIG_DIR/defaults.env"
    fi

    printf 'post-install: persisted existing LLAMA_SERVER_BIN to defaults.env\n'
}

maybe_use_existing_llama_server_runtime() {
    local binary=""
    local backend_hint=""
    local reply=""

    case "${LMM_FORCE_BUILD_RUNTIME:-}" in
        1|true|yes|Y|y) return 1 ;;
    esac

    binary="$(find_existing_llama_server_binary || true)"
    [[ -n "$binary" ]] || return 1
    validate_existing_llama_server_binary "$binary" || return 1

    backend_hint="$(existing_llama_server_backend_hint "$binary")"

    printf 'post-install: found existing llama-server binary:\n'
    printf '  %s\n' "$binary"
    printf 'post-install: existing runtime backend hint: %s\n' "$backend_hint"

    if [[ "$backend_hint" != "unknown" && -n "${primary_backend:-}" && "$backend_hint" != "$primary_backend" ]]; then
        printf 'post-install: existing runtime backend hint does not match detected host backend (%s); continuing with installer-managed build\n' "$primary_backend"
        return 1
    fi

    if [[ -t 0 && -t 1 ]]; then
        if [[ "$backend_hint" == "unknown" && "${primary_backend:-}" == "cuda" ]]; then
            printf 'Existing runtime backend could not be confirmed as CUDA. Use it anyway and skip CUDA build? [y/N] '
            read -r reply || reply=""
            reply="$(to_lower "$reply")"
            if [[ "$reply" != "y" && "$reply" != "yes" ]]; then
                printf 'post-install: existing runtime not selected; continuing with installer-managed build\n'
                return 1
            fi
        else
            printf 'Use this existing llama.cpp runtime instead of building a bundled runtime now? [Y/n] '
            read -r reply || reply=""
            reply="$(to_lower "$reply")"
            if [[ "$reply" == "n" || "$reply" == "no" ]]; then
                printf 'post-install: existing runtime not selected; continuing with installer-managed build\n'
                return 1
            fi
        fi
    else
        case "${LMM_USE_EXISTING_LLAMA_SERVER:-}" in
            1|true|yes|Y|y) ;;
            *) return 1 ;;
        esac
    fi

    persist_existing_llama_server_binary "$binary"
    printf 'post-install: skipped bundled runtime build; existing llama.cpp runtime is now managed outside LMM\n'
    return 0
}

nvcc_supports_cuda_architecture() {
    local arch="$1"

    command -v nvcc >/dev/null 2>&1 || return 2

    # nvcc --list-gpu-arch usually emits lines like compute_75, compute_89.
    # If unsupported by the nvcc version, treat as unknown rather than fatal.
    if ! nvcc --list-gpu-arch >/dev/null 2>&1; then
        return 2
    fi

    if nvcc --list-gpu-arch 2>/dev/null | grep -qx "compute_${arch}"; then
        return 0
    fi

    case "$arch" in
        # Older architectures may not appear in newer nvcc lists, but CMake may
        # still decide a valid PTX/JIT path. Do not kill the installer here.
        50|52|53|60|61|62|70|72|75)
            return 2
            ;;
        *)
            return 1
            ;;
    esac
}

remove_cmake_cuda_arch_arg() {
    export CMAKE_ARGS="$(printf '%s\n' "${CMAKE_ARGS:-}" | sed -E 's/(^|[[:space:]])-DGGML_CUDA_ARCHITECTURES=[^[:space:]]+//g' | xargs)"
}

strip_cmake_cuda_args() {
    export CMAKE_ARGS="$(printf '%s\n' "${CMAKE_ARGS:-}" | sed -E 's/(^|[[:space:]])-DGGML_CUDA_ARCHITECTURES=[^[:space:]]+//g; s/(^|[[:space:]])-DCUDAToolkit_ROOT=[^[:space:]]+//g' | xargs)"
    export LMM_CMAKE_ARGS="$(printf '%s\n' "${LMM_CMAKE_ARGS:-}" | sed -E 's/(^|[[:space:]])-DGGML_CUDA_ARCHITECTURES=[^[:space:]]+//g; s/(^|[[:space:]])-DCUDAToolkit_ROOT=[^[:space:]]+//g' | xargs)"
}

configure_cuda_architectures_for_build() {
    local cuda_arches=""
    local arch=""
    local unsupported=()
    local support_status=0
    local cmake_arch_arg=""

    [[ "${primary_backend:-}" == "cuda" ]] || return 0

    cuda_arches="$(detect_cuda_architectures || true)"

    if [[ -z "$cuda_arches" ]]; then
        printf 'post-install warning: could not detect CUDA compute capability; leaving GGML_CUDA_ARCHITECTURES unset\n' >&2
        printf 'post-install warning: llama.cpp/CMake will attempt CUDA architecture auto-detection\n' >&2
        return 0
    fi

    export GGML_CUDA_ARCHITECTURES="$cuda_arches"

    remove_cmake_cuda_arch_arg
    cmake_arch_arg="-DGGML_CUDA_ARCHITECTURES=${cuda_arches}"
    export CMAKE_ARGS="${CMAKE_ARGS:-} ${cmake_arch_arg}"

    printf 'post-install: detected CUDA architecture(s): %s\n' "$cuda_arches"
    printf 'post-install: exported GGML_CUDA_ARCHITECTURES=%s\n' "$GGML_CUDA_ARCHITECTURES"

    IFS=';' read -r -a _cuda_arch_array <<< "$cuda_arches"
    for arch in "${_cuda_arch_array[@]}"; do
        # Safe under set -e: non-zero return is handled by the if/else.
        if nvcc_supports_cuda_architecture "$arch"; then
            support_status=0
        else
            support_status=$?
        fi

        if [[ "$support_status" -eq 1 ]]; then
            unsupported+=("$arch")
        elif [[ "$support_status" -eq 2 ]]; then
            printf 'post-install warning: nvcc cannot confirm support for sm_%s; skipping strict validation\n' "$arch" >&2
        fi
    done

    if ((${#unsupported[@]} > 0)); then
        printf 'post-install warning: current nvcc does not list support for CUDA architecture(s): %s\n' "${unsupported[*]}" >&2

        for arch in "${unsupported[@]}"; do
            case "$arch" in
                100|101|120)
                    printf 'post-install warning: Blackwell/future GPU detected; CUDA toolkit may need upgrading if build fails.\n' >&2
                    ;;
            esac
        done
    fi

    return 0
}

detect_nvcc_release() {
    command -v nvcc >/dev/null 2>&1 || return 1
    nvcc --version 2>/dev/null | sed -nE 's/.*release ([0-9]+)\.([0-9]+).*/\1.\2/p' | head -n 1
}

cuda_alternative_path_for_version() {
    local version="$1"
    case "$version" in
        12.9) printf '/usr/local/cuda-12.9\n' ;;
        12.8) printf '/usr/local/cuda-12.8\n' ;;
        13.1) printf '/usr/local/cuda-13.1\n' ;;
        *) return 1 ;;
    esac
}

select_cuda_alternative_if_present() {
    local version="$1"
    local cuda_path=""

    cuda_path="$(cuda_alternative_path_for_version "$version" || true)"
    [[ -n "$cuda_path" ]] || return 1

    if [[ ! -d "$cuda_path" ]]; then
        printf 'post-install warning: CUDA path not found: %s\n' "$cuda_path" >&2
        return 1
    fi

    if command -v update-alternatives >/dev/null 2>&1 && update-alternatives --display cuda >/dev/null 2>&1; then
        run_root_cmd update-alternatives --set cuda "$cuda_path" || {
            printf 'post-install warning: failed to select CUDA alternative: %s\n' "$cuda_path" >&2
            return 1
        }
    fi

    case ":$PATH:" in
        *":$cuda_path/bin:"*) ;;
        *) export PATH="$cuda_path/bin:$PATH" ;;
    esac

    case ":${LD_LIBRARY_PATH:-}:" in
        *":$cuda_path/lib64:"*) ;;
        *) export LD_LIBRARY_PATH="$cuda_path/lib64:${LD_LIBRARY_PATH:-}" ;;
    esac
    hash -r 2>/dev/null || true

    printf 'post-install: selected CUDA toolkit path: %s\n' "$cuda_path"
    nvcc --version || true
}

select_default_cuda_if_present() {
    local cuda_path="${CUDA_DEFAULT_PATH:-/usr/local/cuda}"

    [[ -d "$cuda_path" ]] || return 1

    case ":$PATH:" in
        *":$cuda_path/bin:"*) ;;
        *) export PATH="$cuda_path/bin:$PATH" ;;
    esac

    case ":${LD_LIBRARY_PATH:-}:" in
        *":$cuda_path/lib64:"*) ;;
        *) export LD_LIBRARY_PATH="$cuda_path/lib64:${LD_LIBRARY_PATH:-}" ;;
    esac

    hash -r 2>/dev/null || true
    printf 'post-install: selected default CUDA toolkit path: %s\n' "$cuda_path"
}

install_ubuntu_native_cuda_toolkit() {
    [[ "${primary_backend:-}" == "cuda" ]] || return 0
    is_ubuntu_2604_or_newer || return 1
    command -v apt-get >/dev/null 2>&1 || return 1

    local cuda_path="${CUDA_DEFAULT_PATH:-/usr/local/cuda}"

    printf 'post-install: Ubuntu 26.04+ detected; using Ubuntu-native CUDA toolkit package path\n'

    enable_ubuntu_multiverse_best_effort

    install_apt_packages_best_effort \
        build-essential \
        cmake \
        ninja-build \
        git \
        pkg-config \
        libssl-dev \
        gcc-13 \
        g++-13 \
        gcc-14 \
        g++-14 \
        cuda-toolkit

    select_default_cuda_if_present || true

    if command -v nvcc >/dev/null 2>&1; then
        printf 'post-install: nvcc available after Ubuntu-native CUDA toolkit install\n'
        nvcc --version || true
        return 0
    fi

    if [[ -x "$cuda_path/bin/nvcc" ]]; then
        case ":$PATH:" in
            *":$cuda_path/bin:"*) ;;
            *) export PATH="$cuda_path/bin:$PATH" ;;
        esac
        hash -r 2>/dev/null || true
        printf 'post-install: nvcc available at %s/bin/nvcc\n' "$cuda_path"
        "$cuda_path/bin/nvcc" --version || true
        return 0
    fi

    printf 'post-install warning: Ubuntu-native cuda-toolkit did not provide nvcc in PATH\n' >&2
    return 1
}

nvcc_supports_any_detected_cuda_architecture() {
    local cuda_arches=""
    local arch=""

    [[ "${primary_backend:-}" == "cuda" ]] || return 0
    command -v nvcc >/dev/null 2>&1 || return 1

    cuda_arches="${GGML_CUDA_ARCHITECTURES:-$(detect_cuda_architectures || true)}"
    [[ -n "$cuda_arches" ]] || return 0

    if ! nvcc --list-gpu-arch >/dev/null 2>&1; then
        printf 'post-install warning: nvcc cannot list GPU architectures; skipping strict arch validation\n' >&2
        return 0
    fi

    IFS=';' read -r -a _cuda_arch_array <<< "$cuda_arches"
    for arch in "${_cuda_arch_array[@]}"; do
        if nvcc --list-gpu-arch 2>/dev/null | grep -qx "compute_${arch}"; then
            return 0
        fi
    done

    printf 'post-install warning: active nvcc does not list support for detected CUDA arch(es): %s\n' "$cuda_arches" >&2
    return 1
}

configure_cuda_host_compiler() {
    [[ "${primary_backend:-}" == "cuda" ]] || return 0

    if [[ -n "${CUDAHOSTCXX:-}" && -x "${CUDAHOSTCXX:-}" ]]; then
        printf 'post-install: using existing CUDAHOSTCXX=%s\n' "$CUDAHOSTCXX"
        return 0
    fi

    if command -v g++-13 >/dev/null 2>&1 && command -v gcc-13 >/dev/null 2>&1; then
        export CC="$(command -v gcc-13)"
        export CXX="$(command -v g++-13)"
        export CUDAHOSTCXX="$CXX"
        printf 'post-install: selected CUDA host compiler: %s\n' "$CUDAHOSTCXX"
        return 0
    fi

    if command -v g++-14 >/dev/null 2>&1 && command -v gcc-14 >/dev/null 2>&1; then
        export CC="$(command -v gcc-14)"
        export CXX="$(command -v g++-14)"
        export CUDAHOSTCXX="$CXX"
        printf 'post-install: selected CUDA host compiler: %s\n' "$CUDAHOSTCXX"
        return 0
    fi

    printf 'post-install warning: gcc-13/g++-13 or gcc-14/g++-14 not found; CUDA will use default host compiler\n' >&2
}

configure_cuda_toolkit_for_build() {
    [[ "${primary_backend:-}" == "cuda" ]] || return 0

    local nvcc_release=""
    local cuda_arches="${GGML_CUDA_ARCHITECTURES:-}"

    if [[ "${primary_backend:-}" != "cuda" ]]; then
        return 0
    fi

    if cuda_arches_need_legacy_toolkit; then
        configure_legacy_cuda_toolkit_for_build
        if [[ "${primary_backend:-}" == "cuda" ]]; then
            configure_cuda_host_compiler
            nvcc_release="$(detect_nvcc_release || true)"
            printf 'post-install: active nvcc release: %s\n' "${nvcc_release:-unknown}"
        fi
        return 0
    fi

    if is_ubuntu_2604_or_newer; then
        if install_ubuntu_native_cuda_toolkit; then
            configure_cuda_host_compiler

            nvcc_release="$(detect_nvcc_release || true)"
            printf 'post-install: active nvcc release: %s\n' "${nvcc_release:-unknown}"

            if ! nvcc_supports_any_detected_cuda_architecture; then
                printf 'post-install warning: active CUDA toolkit may not support detected CUDA architecture; CUDA build may fail\n' >&2
            fi

            return 0
        fi

        printf 'post-install warning: Ubuntu-native CUDA toolkit setup did not make nvcc available; falling back to CPU runtime\n' >&2
        primary_backend="cpu"
        unset GGML_CUDA_ARCHITECTURES
        strip_cmake_cuda_args
        return 0
    fi

    bootstrap_nvidia_cuda_apt_repo

    # Install general build deps and preferred host compilers first.
    if command -v apt-get >/dev/null 2>&1; then
        install_apt_packages_best_effort \
            build-essential \
            cmake \
            ninja-build \
            git \
            pkg-config \
            gcc-13 \
            g++-13 \
            gcc-14 \
            g++-14
    fi

    nvcc_release="$(detect_nvcc_release || true)"

    # For Blackwell/future architectures, CUDA 12.9 may not be enough.
    # Keep or install the newer toolkit lane, then let the real build decide.
    if cuda_arches_need_modern_toolkit "$cuda_arches"; then
        printf 'post-install: modern CUDA architecture detected (%s); keeping/preparing modern CUDA toolkit lane\n' "$cuda_arches"
        if [[ -z "$nvcc_release" ]] && command -v apt-get >/dev/null 2>&1; then
            install_apt_packages_best_effort cuda-toolkit-13-1 cuda-nvcc-13-1
            select_cuda_alternative_if_present "13.1" || true
        fi
    else
        # CUDA 13.1 has known rsqrt/rsqrtf noexcept conflicts with newer glibc.
        # Prefer CUDA 12.9 for non-Blackwell systems when current nvcc is missing
        # or is CUDA 13.1.
        if [[ -z "$nvcc_release" || "$nvcc_release" == "13.1" ]]; then
            printf 'post-install: CUDA nvcc release is "%s"; checking for CUDA 12.9 fallback\n' "${nvcc_release:-missing}"

            if command -v apt-get >/dev/null 2>&1; then
                install_apt_packages_best_effort cuda-toolkit-12-9 cuda-nvcc-12-9
            fi

            select_cuda_alternative_if_present "12.9" || {
                printf 'post-install warning: CUDA 12.9 was not selectable; keeping current CUDA toolkit\n' >&2
            }
        fi
    fi

    # If still no nvcc, try CUDA 12.8 as a non-Blackwell fallback.
    if ! command -v nvcc >/dev/null 2>&1 && ! cuda_arches_need_modern_toolkit "$cuda_arches"; then
        if command -v apt-get >/dev/null 2>&1; then
            install_apt_packages_best_effort cuda-toolkit-12-8 cuda-nvcc-12-8
        fi
        select_cuda_alternative_if_present "12.8" || true
    fi

    if ! command -v nvcc >/dev/null 2>&1; then
        printf 'post-install: version-pinned CUDA toolkit packages unavailable; trying generic/current CUDA toolkit packages\n'

        if command -v apt-get >/dev/null 2>&1; then
            install_apt_packages_best_effort \
                cuda-toolkit \
                cuda-nvcc \
                cuda-compiler \
                libcublas-dev
        fi

        select_default_cuda_if_present || true
    fi

    configure_cuda_host_compiler

    if ! command -v nvcc >/dev/null 2>&1; then
        warn_cuda_apt_visibility_if_nvcc_missing
        printf 'post-install warning: nvcc still unavailable after CUDA toolkit setup; falling back to CPU runtime\n' >&2
        primary_backend="cpu"
        unset GGML_CUDA_ARCHITECTURES
        strip_cmake_cuda_args
        return 0
    fi

    nvcc_release="$(detect_nvcc_release || true)"
    printf 'post-install: active nvcc release: %s\n' "${nvcc_release:-unknown}"

    if [[ "$nvcc_release" == "13.1" ]] && ! cuda_arches_need_modern_toolkit "$cuda_arches"; then
        printf 'post-install warning: CUDA 13.1 remains active on a non-Blackwell GPU. If CMakeCUDACompilerId.cu fails with rsqrt/rsqrtf, install/select CUDA 12.9 or use CPU fallback.\n' >&2
    fi

    if ! nvcc_supports_any_detected_cuda_architecture; then
        printf 'post-install warning: active CUDA toolkit may not support this GPU architecture; CUDA build may fail and CPU fallback will be used\n' >&2
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
#   - Detects CUDA compute capability and exports GGML_CUDA_ARCHITECTURES
#   - Retries CPU fallback automatically if GPU build fails
#   - Interactively asks before building in terminal sessions
build_runtime_during_install() {
    local bin="$BIN_DIR/llama-model"
    [[ -x "$bin" ]] || { printf 'post-install: skipping runtime build — %s not installed yet\n' "$bin" >&2; return 0; }

    printf 'post-install: detecting host GPU capabilities for runtime build...\n'

    local has_gpu="no"
    local primary_backend=""
    local os
    os="$(uname -s)"

    case "$os" in
        Linux)
            # Phase 0: Physical hardware check (works with zero drivers installed)
            if grep -q '0x10de' /sys/bus/pci/devices/*/vendor 2>/dev/null; then
                has_gpu="yes"
                primary_backend="cuda"
                printf 'post-install: NVIDIA GPU detected via PCI vendor ID (0x10de)\n'
            elif command -v lspci >/dev/null 2>&1 && lspci 2>/dev/null | grep -qi 'nvidia\|3d controller\|vga compatible.*nvidia'; then
                has_gpu="yes"
                primary_backend="cuda"
                printf 'post-install: NVIDIA GPU detected via lspci\n'
            fi

            # Phase 1: Driver/runtime checks
            if [[ "$has_gpu" != "yes" ]]; then
                if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
                    has_gpu="yes"
                    primary_backend="cuda"
                    printf 'post-install: NVIDIA GPU detected via nvidia-smi\n'
                elif [[ -e /dev/nvidia0 ]] || [[ -e /dev/nvidiactl ]]; then
                    has_gpu="yes"
                    primary_backend="cuda"
                    printf 'post-install: NVIDIA GPU detected via /dev/nvidia* device nodes\n'
                elif ldconfig -p 2>/dev/null | grep -q 'libvulkan\.so'; then
                    has_gpu="yes"
                    primary_backend="vulkan"
                    printf 'post-install: Vulkan GPU detected via ldconfig\n'
                fi
            fi

            # Phase 2: Package/kernel fallbacks
            if [[ "$has_gpu" != "yes" ]]; then
                if dpkg -l 2>/dev/null | grep -qi 'nvidia'; then
                    has_gpu="yes"
                    primary_backend="cuda"
                    printf 'post-install: NVIDIA GPU detected via installed packages\n'
                elif ls /sys/bus/pci/drivers/nvidia/ 2>/dev/null | grep -q .; then
                    has_gpu="yes"
                    primary_backend="cuda"
                    printf 'post-install: NVIDIA GPU detected via sysfs driver binding\n'
                elif modprobe -n nvidia 2>/dev/null; then
                    has_gpu="yes"
                    primary_backend="cuda"
                    printf 'post-install: NVIDIA GPU detected via available kernel module\n'
                fi
            fi
            ;;
        Darwin)
            has_gpu="yes"
            primary_backend="metal"
            ;;
    esac

    # Install nvidia-smi if CUDA detected but tool missing
    if [[ "$primary_backend" == "cuda" ]] && ! command -v nvidia-smi >/dev/null 2>&1; then
        printf 'post-install: nvidia-smi not found; installing for GPU detection...\n'
        if [[ -t 0 && -t 1 ]]; then
            printf 'Would you like to install nvidia-smi now? [Y/n] '
            local reply
            read -r reply || reply=""
            reply="$(to_lower "$reply")"
            if [[ "$reply" != "n" && "$reply" != "no" ]]; then
                if command -v apt-get >/dev/null 2>&1; then
                    printf 'post-install: installing nvidia-utils-580 via apt-get...\n'
                    (apt-get update -qq && apt-get install -y -qq nvidia-utils-580) 2>/dev/null || \
                        (sudo apt-get update -qq && sudo apt-get install -y -qq nvidia-utils-580) 2>/dev/null || \
                        printf 'post-install: failed to install nvidia-utils-580; install manually: sudo apt install nvidia-utils-580\n'
                elif command -v dnf >/dev/null 2>&1; then
                    printf 'post-install: installing nvidia-modprobe via dnf...\n'
                    (dnf install -y nvidia-modprobe) 2>/dev/null || \
                        (sudo dnf install -y nvidia-modprobe) 2>/dev/null || \
                        printf 'post-install: failed to install nvidia-modprobe; install manually: sudo dnf install nvidia-modprobe\n'
                fi
                if command -v nvidia-smi >/dev/null 2>&1; then
                    printf 'post-install: nvidia-smi installed successfully\n'
                else
                    printf 'post-install: nvidia-smi not found after install; you may need to reboot or install the full NVIDIA driver\n'
                fi
            fi
        else
            printf 'post-install: install nvidia-smi manually (sudo apt install nvidia-utils) and rerun: llama-model build-runtime --backend cuda\n'
        fi
    fi

    if [[ "$has_gpu" != "yes" ]]; then
        printf 'post-install: no GPU runtime detected on this host; building CPU fallback only\n'
        primary_backend="cpu"
    fi

    if [[ "$has_gpu" == "yes" ]] && maybe_use_existing_llama_server_runtime; then
        return 0
    fi

    if [[ -t 0 && -t 1 ]]; then
        # Interactive: show what we're doing and ask
        printf 'post-install: host %s backend detected\n' "$primary_backend"
        if [[ "$primary_backend" == "cuda" ]] && ! command -v nvcc >/dev/null 2>&1; then
            printf 'post-install: CUDA-capable NVIDIA GPU detected, but nvcc is missing.\n'
            printf 'post-install: installer-managed setup will use CUDA 11.8 toolkit-only for legacy GPUs when approved, Ubuntu-native cuda-toolkit on Ubuntu 26.04+, otherwise NVIDIA CUDA apt repo packages.\n'
            printf 'post-install: it will install build tools, select gcc/g++ 13 or 14 as CUDA host compiler, build CUDA runtime, and fall back to CPU if CUDA fails.\n'
        fi
        printf 'Proceed with installer-managed build dependency setup and local llama.cpp runtime compile now? [Y/n] '
        reply=""
        read -r reply || reply=""
        reply="$(to_lower "$reply")"
        if [[ "$reply" == "n" || "$reply" == "no" ]]; then
            printf 'post-install: runtime build skipped by user\n'
            return 0
        fi
    else
        # Non-interactive / headless: only auto-build if deps are trivially
        # available (no sudo prompts, no user interaction needed).
        if [[ "$primary_backend" == "cpu" ]]; then
            printf 'post-install: non-interactive install on CPU-only host; building CPU runtime\n'
        elif [[ "$primary_backend" == "cuda" ]] && ! command -v nvcc >/dev/null 2>&1; then
            printf 'post-install: CUDA host detected but nvcc not in PATH; attempting CUDA toolkit setup before build\n'
        elif [[ "$primary_backend" == "cuda" ]] && command -v nvcc >/dev/null 2>&1; then
            # nvcc is available - proceed with GPU build
            printf 'post-install: CUDA host with nvcc available; building CUDA runtime\n'
        elif [[ "$primary_backend" == "vulkan" ]] && ! command -v glslc >/dev/null 2>&1 && ! command -v glslangValidator >/dev/null 2>&1; then
            printf 'post-install: Vulkan host detected but SDK tools not in PATH; skipping GPU build\n'
            printf 'note: set LMM_AUTO_BUILD_RUNTIME=1 to force, or run manually after installing Vulkan SDK\n'
            primary_backend="cpu"
            printf 'post-install: falling back to CPU-only runtime\n'
        elif [[ "$primary_backend" == "metal" ]] && ! xcode-select -p >/dev/null 2>&1; then
            printf 'post-install: macOS Metal host detected but Xcode CLT not installed; skipping GPU build\n'
            printf 'note: install Xcode CLT with: xcode-select --install\n'
            primary_backend="cpu"
            printf 'post-install: falling back to CPU-only runtime\n'
        else
            printf 'post-install: non-interactive install with %s build tools available; building %s runtime\n' "$primary_backend" "$primary_backend"
        fi
    fi

    configure_cuda_architectures_for_build

    if [[ "$primary_backend" == "cuda" ]] && cuda_arches_need_legacy_toolkit; then
        configure_legacy_cuda_toolkit_for_build
    elif [[ "$primary_backend" == "cuda" ]]; then
        configure_cuda_toolkit_for_build
    fi

    # Print exact compiler contract for CUDA builds to catch GCC/CUDA mismatches.
    if [[ "$primary_backend" == "cuda" ]]; then
        printf 'post-install: CUDA compiler: %s\n' "$(command -v nvcc || true)"
        nvcc --version || true

        printf 'post-install: host C compiler: %s\n' "${CC:-$(command -v cc || true)}"
        "${CC:-cc}" --version | head -n 1 || true

        printf 'post-install: host C++ compiler: %s\n' "${CXX:-$(command -v c++ || true)}"
        "${CXX:-c++}" --version | head -n 1 || true

        if [[ -n "${CUDAHOSTCXX:-}" ]]; then
            printf 'post-install: CUDAHOSTCXX: %s\n' "$CUDAHOSTCXX"
            "$CUDAHOSTCXX" --version | head -n 1 || true
        fi
    fi

    # Force the build to write into the installed app share, not the source
    # checkout.  Without this, build-runtime resolves APP_ROOT to the repo
    # directory (because web/ exists there) and writes binaries to the wrong
    # location.
    if ! LLAMA_SERVER_RUNTIME_DIR="${APP_SHARE_DIR}/runtime" \
         LLAMA_AUTO_INSTALL_DEPS=1 \
         "$bin" build-runtime --backend "$primary_backend"; then
        printf 'post-install: %s runtime build failed\n' "$primary_backend" >&2

        if [[ "$primary_backend" != "cpu" ]]; then
            printf 'post-install: retrying CPU fallback runtime\n' >&2
            primary_backend="cpu"
            unset GGML_CUDA_ARCHITECTURES
            strip_cmake_cuda_args

            if ! LLAMA_SERVER_RUNTIME_DIR="${APP_SHARE_DIR}/runtime" \
                 LLAMA_AUTO_INSTALL_DEPS=1 \
                 "$bin" build-runtime --backend cpu; then
                printf 'post-install: CPU fallback runtime build also failed\n' >&2
                printf 'post-install: run "%s build-runtime --backend auto" manually after fixing dependencies\n' "$bin" >&2
                return 0
            fi
        else
            printf 'post-install: run "%s build-runtime --backend auto" manually after fixing dependencies\n' "$bin" >&2
            return 0
        fi
    fi

    # Post-build validation: ldd + --version checks
    local runtime_dir="${APP_SHARE_DIR}/runtime/llama-server"
    local mark_runtime_invalid=0
    local runtime_binaries=()
    local valid_runtime_binaries=()
    local b=""
    local payload_binary=""
    local backend_runtime_dir=""

    backend_runtime_dir="$(find "$runtime_dir" -maxdepth 1 -type d -name "*-${primary_backend}" -print -quit 2>/dev/null || true)"

    if [[ -n "$backend_runtime_dir" ]] && [[ -x "$backend_runtime_dir/llama-server" ]]; then
        runtime_binaries+=("$backend_runtime_dir/llama-server")

        for b in "${runtime_binaries[@]}"; do
            payload_binary="${b}.bin"
            if [[ -x "$payload_binary" ]]; then
                missing="$(ldd "$payload_binary" 2>&1 | grep 'not found' | grep -E 'lib(ggml|llama|mtmd|cuda|cudart|cublas|vulkan|MoltenVK|metal)' || true)"
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
    [[ -f "$mcp_dir/dist/index.js" ]] && [[ -d "$mcp_dir/node_modules/domino" ]] && return 0

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
        # esbuild needs its platform binary from optionalDependencies;
        # --omit=optional skipped it, so install it explicitly without scripts
        npm install @esbuild/linux-x64 --save-optional --ignore-scripts --no-audit --fund=false 2>/dev/null || true
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
        printf 'LLAMA_MODEL_GATEWAY_LOG=%s/models/lmm-gateway.log\n' "$HOME" >>"$tmp"
    fi
    if ! defaults_has_key LLAMA_MODEL_GATEWAY_FAST_ENABLED "$tmp"; then
        printf 'LLAMA_MODEL_GATEWAY_FAST_ENABLED=1\n' >>"$tmp"
    fi
    if ! defaults_has_key LLAMA_MODEL_GATEWAY_FAST_PORT "$tmp"; then
        printf 'LLAMA_MODEL_GATEWAY_FAST_PORT=4011\n' >>"$tmp"
    fi
    if ! defaults_has_key LLAMA_MODEL_GATEWAY_FAST_LOG "$tmp"; then
        printf 'LLAMA_MODEL_GATEWAY_FAST_LOG=%s/models/lmm-gateway-fast.log\n' "$HOME" >>"$tmp"
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
    [[ -f "$ROOT_DIR/bin/llama-model" ]] || {
        printf 'error: installer payload is missing bin/llama-model\n' >&2
        missing=1
    }
    [[ -f "$ROOT_DIR/config/defaults.env.example" ]] || {
        printf 'error: installer payload is missing config/defaults.env.example\n' >&2
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

# Learning Loop — initialize config directory and seed lessons
LMM_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/llama-model-manager"
mkdir -p "$LMM_CONFIG_DIR"
if [[ ! -f "$LMM_CONFIG_DIR/lessons.md" ]] && [[ -f "$APP_SHARE_DIR/integrations/learning-loop/templates/lessons.md" ]]; then
    cp "$APP_SHARE_DIR/integrations/learning-loop/templates/lessons.md" "$LMM_CONFIG_DIR/lessons.md"
    printf 'initialized Learning Loop lessons: %s/lessons.md\n' "$(compact_home_path "$LMM_CONFIG_DIR")"
fi
if [[ ! -f "$LMM_CONFIG_DIR/agent_state.json" ]]; then
    python3 -c "
import json, time, os
state = {
    'per_domain_strategies': {},
    'novelty_scores': {},
    'session_count': 0,
    'total_tasks': 0,
    'created_at': time.time(),
    'updated_at': time.time()
}
os.makedirs('$LMM_CONFIG_DIR', exist_ok=True)
with open('$LMM_CONFIG_DIR/agent_state.json', 'w') as f:
    json.dump(state, f, indent=2)
"
    printf 'initialized Learning Loop persistence: %s/agent_state.json\n' "$(compact_home_path "$LMM_CONFIG_DIR")"
fi

# Step 1: Build bundled llama.cpp runtime for the host.  This replaces the old
# "no runtime shipped" gap — we now compile GPU/CPU binaries during install so
# fresh installs can actually run models on their hardware.
build_runtime_during_install
install_basedpyright_during_install

# Step 2: Merge pre-built runtime bundles from the source tree (rare: only
# if the developer built them locally before packaging).  The install build
# from Step 1 already wrote to $APP_SHARE_DIR/runtime, so we merge without
# overwriting the just-validated host runtime.
if [[ -d "$ROOT_DIR/runtime" ]]; then
    while IFS= read -r -d '' src; do
        rel="${src#$ROOT_DIR/runtime/}"
        dst="$APP_SHARE_DIR/runtime/$rel"
        if [[ ! -e "$dst" ]]; then
            mkdir -p "$(dirname "$dst")"
            cp -a "$src" "$dst"
        fi
    done < <(find "$ROOT_DIR/runtime" -mindepth 1 -print0)
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

# Migrate deprecated llama-server flags in existing models.tsv rows.
# Creates a timestamped backup before in-place migration.
migrate_models_tsv_deprecated_flags() {
    local file="$1"
    local tmp
    local modified=0
    local line
    local row_alias
    local path_field
    local extra_field
    local rest

    tmp="$(mktemp)"

    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ -z "$line" || "${line:0:1}" == "#" ]]; then
            printf '%s\n' "$line" >>"$tmp"
            continue
        fi

        # TSV: alias \t path \t extra_args \t context \t ngl \t batch \t threads \t parallel \t device \t notes
        row_alias="${line%%$'\t'*}"
        rest="${line#*$'\t'}"
        path_field="${rest%%$'\t'*}"
        rest="${rest#*$'\t'}"
        extra_field="${rest%%$'\t'*}"
        rest="${rest#*$'\t'}"

        if [[ "$extra_field" == *"--chat-templateFile"* ]]; then
            extra_field="${extra_field//--chat-templateFile/--chat-template-file}"
            modified=1
        fi

        printf '%s\t%s\t%s\t%s\n' "$row_alias" "$path_field" "$extra_field" "$rest" >>"$tmp"
    done <"$file"

    if [[ "$modified" -eq 1 ]]; then
        cp -a "$file" "${file}.pre-migrate-$(date +%Y%m%d%H%M%S)"
        mv "$tmp" "$file"
        printf 'migrated deprecated flags in %s (backup saved)\n' "$(compact_home_path "$file")"
    else
        rm -f "$tmp"
    fi
}

if [[ ! -f "$CONFIG_DIR/models.tsv" ]]; then
    write_empty_registry "$CONFIG_DIR/models.tsv"
    printf 'installed %s\n' "$CONFIG_DIR/models.tsv"
elif is_placeholder_seed_registry "$CONFIG_DIR/models.tsv"; then
    write_empty_registry "$CONFIG_DIR/models.tsv"
    printf 'migrated %s\n' "$CONFIG_DIR/models.tsv"
else
    printf 'kept existing %s\n' "$CONFIG_DIR/models.tsv"
    migrate_models_tsv_deprecated_flags "$CONFIG_DIR/models.tsv"
fi
if [[ -f "$ROOT_DIR/desktop/llama-model-manager.desktop" ]]; then
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
else
    printf 'warning: desktop file not found at %s, skipping desktop integration\n' "$ROOT_DIR/desktop/llama-model-manager.desktop" >&2
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
printf '  9. Sync GlyphOS AI Compute if you use it: llama-model sync-glyphos\n'
printf ' 10. Bundled public GlyphOS AI Compute package: %s/integrations/public-glyphos-ai-compute\n' "$(compact_home_path "$APP_SHARE_DIR")"
printf ' 11. Experimental CUDA unified-memory fallback: set GGML_CUDA_ENABLE_UNIFIED_MEMORY=1 in %s/defaults.env to try larger context/KV/compute allocations through system RAM\n' "$(compact_home_path "$CONFIG_DIR")"
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
    if [[ -d "$runtime_dir" ]] && \
       find "$runtime_dir" -maxdepth 2 -name 'llama-server' -type f -executable -print -quit 2>/dev/null | grep -q .; then
        has_runtime="yes"
    fi
    if [[ "$has_runtime" != "yes" ]]; then
        printf '\nNo llama.cpp runtime was built during install. Compile one now? [Y/n] '
        read -r reply || reply=""
        reply="$(to_lower "$reply")"
        if [[ -z "$reply" || "$reply" == "y" || "$reply" == "yes" ]]; then
            if "$BIN_DIR/llama-model" build-runtime --backend auto; then
                printf 'Local runtime build completed.\n'
            else
                printf 'Runtime build did not complete. Resolve any missing dependencies and rerun: llama-model build-runtime --backend auto\n' >&2
            fi
        fi
    fi
fi
