#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$ROOT_DIR/bin/llama-model"

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

assert_contains() {
    local haystack="$1"
    local needle="$2"
    [[ "$haystack" == *"$needle"* ]] || fail "expected output to contain: $needle"
}

assert_not_contains() {
    local haystack="$1"
    local needle="$2"
    [[ "$haystack" != *"$needle"* ]] || fail "expected output not to contain: $needle"
}

make_env() {
    local tmp="$1"
    mkdir -p "$tmp/home" "$tmp/config/llama-server" "$tmp/state" "$tmp/runtime"
    cat >"$tmp/config/llama-server/defaults.env" <<'EOF'
LLAMA_SERVER_BIN=
LLAMA_SERVER_DEVICE=
LLAMA_SERVER_PORT=19081
LLAMA_SERVER_LOG=
GGML_CUDA_ENABLE_UNIFIED_MEMORY=
EOF
}

make_model() {
    local path="$1"
    mkdir -p "$(dirname "$path")"
    : >"$path"
}

make_bundle() {
    local runtime_dir="$1"
    local bundle_id="$2"
    local backend="$3"
    local extra_manifest="${4:-}"
    local bundle_dir="$runtime_dir/llama-server/$bundle_id"

    mkdir -p "$bundle_dir"
    cat >"$bundle_dir/llama-server" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
    cat >"$bundle_dir/llama-server.compat.env" <<EOF
LLAMA_BUNDLE_OS=linux
LLAMA_BUNDLE_ARCH=x86_64
LLAMA_BUNDLE_BACKEND=$backend
LLAMA_BUNDLE_LABEL=$backend
$extra_manifest
EOF
    chmod +x "$bundle_dir/llama-server"
}

run_doctor() {
    local tmp="$1"
    shift
    env \
        HOME="$tmp/home" \
        PATH="/usr/bin:/bin" \
        XDG_CONFIG_HOME="$tmp/config" \
        XDG_STATE_HOME="$tmp/state" \
        LLAMA_SERVER_RUNTIME_DIR="$tmp/runtime" \
        "$@" \
        "$BIN" doctor
}

run_cli() {
    local tmp="$1"
    shift
    env \
        HOME="$tmp/home" \
        PATH="/usr/bin:/bin" \
        XDG_CONFIG_HOME="$tmp/config" \
        XDG_STATE_HOME="$tmp/state" \
        LLAMA_SERVER_RUNTIME_DIR="$tmp/runtime" \
        "$BIN" "$@"
}

test_host_match_accepts_bundled_backend() {
    local tmp
    local output

    tmp="$(mktemp -d)"
    make_env "$tmp"
    make_bundle "$tmp/runtime" "linux-x86_64-cuda" "cuda" "LLAMA_BUNDLE_CUDA_CC=8.6"

    output="$(run_doctor "$tmp" LLAMA_HOST_OS=linux LLAMA_HOST_ARCH=x86_64 LLAMA_HOST_BACKENDS=cpu,cuda LLAMA_HOST_CUDA_CC=8.6)"
    assert_contains "$output" "binary_ok: yes"
    assert_contains "$output" "binary_source: bundled"
    assert_contains "$output" "binary_backend: cuda"
    assert_contains "$output" "binary_status: compatible"
}

test_host_mismatch_rejects_bundled_backend() {
    local tmp
    local output
    local model
    local err

    tmp="$(mktemp -d)"
    make_env "$tmp"
    make_bundle "$tmp/runtime" "linux-x86_64-cuda" "cuda" "LLAMA_BUNDLE_CUDA_CC=5.2"
    model="$tmp/models/test.gguf"
    make_model "$model"

    output="$(run_doctor "$tmp" LLAMA_HOST_OS=linux LLAMA_HOST_ARCH=x86_64 LLAMA_HOST_BACKENDS=cpu,cuda LLAMA_HOST_CUDA_CC=8.6)"
    assert_contains "$output" "binary_ok: no"
    assert_contains "$output" "binary_status: unavailable"
    assert_contains "$output" "compute capability"

    err="$tmp/switch.err"
    if env \
        HOME="$tmp/home" \
        PATH="/usr/bin:/bin" \
        XDG_CONFIG_HOME="$tmp/config" \
        XDG_STATE_HOME="$tmp/state" \
        LLAMA_SERVER_RUNTIME_DIR="$tmp/runtime" \
        LLAMA_HOST_OS=linux \
        LLAMA_HOST_ARCH=x86_64 \
        LLAMA_HOST_BACKENDS=cpu,cuda \
        LLAMA_HOST_CUDA_CC=8.6 \
        "$BIN" switch "$model" >"$tmp/switch.out" 2>"$err"; then
        fail "expected switch to fail for incompatible bundled CUDA runtime"
    fi
    assert_contains "$(cat "$err")" "build-runtime"
}

test_cpu_fallback_selected_when_gpu_bundle_is_rejected() {
    local tmp
    local output

    tmp="$(mktemp -d)"
    make_env "$tmp"
    make_bundle "$tmp/runtime" "linux-x86_64-cuda" "cuda" "LLAMA_BUNDLE_CUDA_CC=5.2"
    make_bundle "$tmp/runtime" "linux-x86_64-cpu" "cpu"

    output="$(run_doctor "$tmp" LLAMA_HOST_OS=linux LLAMA_HOST_ARCH=x86_64 LLAMA_HOST_BACKENDS=cpu,cuda LLAMA_HOST_CUDA_CC=8.6)"
    assert_contains "$output" "binary_ok: yes"
    assert_contains "$output" "binary_source: bundled-cpu-fallback"
    assert_contains "$output" "binary_backend: cpu"
    assert_contains "$output" "binary_status: fallback"
}

test_no_safe_binary_path_reports_build_guidance() {
    local tmp
    local output

    tmp="$(mktemp -d)"
    make_env "$tmp"

    output="$(run_doctor "$tmp" LLAMA_HOST_OS=linux LLAMA_HOST_ARCH=x86_64 LLAMA_HOST_BACKENDS=cpu)"
    assert_contains "$output" "binary_ok: no"
    assert_contains "$output" "binary_status: unavailable"
    assert_contains "$output" "binary_guidance: Run \`llama-model build-runtime\`"
}

test_docs_no_longer_imply_universal_gpu_binary() {
    local readme
    local help
    local defaults
    local web_index
    local install_script

    readme="$(cat "$ROOT_DIR/README.md")"
    help="$(cat "$ROOT_DIR/config/HELP.txt")"
    defaults="$(cat "$ROOT_DIR/config/defaults.env.example")"
    web_index="$(cat "$ROOT_DIR/web/index.html")"
    install_script="$(cat "$ROOT_DIR/install.sh")"

    assert_contains "$readme" "backend-, platform-, and architecture-specific"
    assert_contains "$readme" "shows the install commands it plans to run"
    assert_contains "$readme" "llama-model sync-opencode --preset long-run"
    assert_contains "$readme" "llama-model sync-openclaw"
    assert_contains "$readme" "llama-model sync-claude"
    assert_contains "$readme" "llama-model sync-glyphos"
    assert_contains "$help" "llama-model build-runtime --backend auto"
    assert_contains "$help" "llama-model sync-opencode --preset balanced|long-run"
    assert_contains "$help" "llama-model sync-openclaw"
    assert_contains "$help" "llama-model sync-claude"
    assert_contains "$help" "llama-model claude-gateway start"
    assert_contains "$help" "llama-model sync-glyphos"
    assert_contains "$help" "llama-model download-jobs"
    assert_contains "$help" "llama-model download-cancel <job_id>"
    assert_contains "$defaults" "OPENCLAW_PROFILE="
    assert_contains "$defaults" "CLAUDE_GATEWAY_PORT=4000"
    assert_contains "$defaults" "CLAUDE_GATEWAY_UPSTREAM_TIMEOUT_SECONDS=1800"
    assert_contains "$defaults" "GGML_CUDA_ENABLE_UNIFIED_MEMORY="
    assert_not_contains "$defaults" "LLAMA_SERVER_DEVICE=cuda0"
    assert_contains "$web_index" "Claude Gateway Timeout (s)"
    assert_contains "$web_index" "Remote Models"
    assert_contains "$web_index" "Download Jobs"
    assert_contains "$web_index" "Observed Glyph Routes"
    assert_contains "$web_index" "Control-plane actions only"
    assert_contains "$web_index" "toggle-activity-panel"
    assert_contains "$web_index" "glyphos-badge"
    assert_contains "$web_index" "CUDA Unified Memory (experimental)"
    assert_not_contains "$web_index" "GPU-aware defaults"
    assert_contains "$install_script" "Would you like to check/install build dependencies"
    assert_contains "$install_script" "llama-model sync-opencode"
    assert_contains "$install_script" "llama-model sync-openclaw"
    assert_contains "$install_script" "llama-model sync-claude"
    assert_contains "$install_script" "llama-model sync-glyphos"
    assert_contains "$readme" "integrations/public-glyphos-ai-compute/"
    assert_contains "$help" "bundled public copy lives under integrations/public-glyphos-ai-compute/"
    assert_contains "$install_script" "Bundled public GlyphOS AI Compute package"
    assert_contains "$install_script" "GGML_CUDA_ENABLE_UNIFIED_MEMORY=1"
}

test_installers_support_bootstrap_tty_handoff_and_empty_registry_seed() {
    local bootstrap
    local tmp
    local models
    local app_py
    local app_js

    bootstrap="$(cat "$ROOT_DIR/install-bootstrap.sh")"
    assert_contains "$bootstrap" "TTY_REATTACH_OK=\"no\""
    assert_contains "$bootstrap" "if sh -c 'exec </dev/tty' 2>/dev/null; then"
    assert_contains "$bootstrap" 'exec bash "$SOURCE_DIR/install.sh" </dev/tty'

    tmp="$(mktemp -d)"
    mkdir -p "$tmp/home/Desktop" "$tmp/config" "$tmp/data"

    env \
        HOME="$tmp/home" \
        XDG_CONFIG_HOME="$tmp/config" \
        XDG_DATA_HOME="$tmp/data" \
        bash "$ROOT_DIR/install.sh" >/dev/null

    models="$(cat "$tmp/config/llama-server/models.tsv")"
    defaults_installed="$(cat "$tmp/config/llama-server/defaults.env")"
    assert_contains "$models" "# alias<TAB>model_path<TAB>extra_args<TAB>context<TAB>ngl<TAB>batch<TAB>threads<TAB>parallel<TAB>device<TAB>notes"
    assert_contains "$defaults_installed" "GGML_CUDA_ENABLE_UNIFIED_MEMORY="
    assert_not_contains "$models" "qwen36-35b-q2"
    assert_not_contains "$models" "gemma4-e4b-q8"

    app_py="$(cat "$ROOT_DIR/web/app.py")"
    app_js="$(cat "$ROOT_DIR/web/app.js")"
    assert_contains "$app_py" '"home_dir": str(self.home)'
    assert_contains "$app_py" '"dashboard_started_at": self.started_at'
    assert_contains "$app_py" 'GGML_CUDA_ENABLE_UNIFIED_MEMORY'
    assert_contains "$app_js" 'function displayPath(path) {'
    assert_contains "$app_js" 'function renderObservedGlyphRoutes'
    assert_contains "$app_js" 'llama-model-manager.activityPanelVisible'
    assert_contains "$app_js" 'default-cuda-unified-memory'
    assert_contains "$app_js" 'return `~/${value.slice(homeDir.length + 1)}`;'
}


test_install_migrates_placeholder_seed_registry() {
    local tmp
    local models

    tmp="$(mktemp -d)"
    mkdir -p "$tmp/home/Desktop" "$tmp/config/llama-server" "$tmp/data"
    cp "$ROOT_DIR/config/models.tsv.example" "$tmp/config/llama-server/models.tsv"

    env \
        HOME="$tmp/home" \
        XDG_CONFIG_HOME="$tmp/config" \
        XDG_DATA_HOME="$tmp/data" \
        bash "$ROOT_DIR/install.sh" >/dev/null

    models="$(cat "$tmp/config/llama-server/models.tsv")"
    assert_contains "$models" "# alias<TAB>model_path<TAB>extra_args<TAB>context<TAB>ngl<TAB>batch<TAB>threads<TAB>parallel<TAB>device<TAB>notes"
    assert_not_contains "$models" "qwen36-35b-q2"
    assert_not_contains "$models" "qwen35-9b-q8"
    assert_not_contains "$models" "gemma4-e4b-q8"
}

test_install_preserves_real_registry_entries() {
    local tmp
    local models

    tmp="$(mktemp -d)"
    mkdir -p "$tmp/home/Desktop" "$tmp/config/llama-server" "$tmp/data"
    cat >"$tmp/config/llama-server/models.tsv" <<'EOF_MODELS'
# alias<TAB>model_path<TAB>extra_args<TAB>context<TAB>ngl<TAB>batch<TAB>threads<TAB>parallel<TAB>device<TAB>notes
my-model	/home/test/models/my-model.gguf		8192	0	512	8	1	cpu	local entry
EOF_MODELS

    env \
        HOME="$tmp/home" \
        XDG_CONFIG_HOME="$tmp/config" \
        XDG_DATA_HOME="$tmp/data" \
        bash "$ROOT_DIR/install.sh" >/dev/null

    models="$(cat "$tmp/config/llama-server/models.tsv")"
    assert_contains "$models" "my-model"
    assert_contains "$models" "/home/test/models/my-model.gguf"
    assert_not_contains "$models" "qwen36-35b-q2"
}

test_dependency_install_preview_exists() {
    local preview

    # shellcheck disable=SC1090
    source "$BIN"
    preview="$(preview_dependency_install_commands apt-get git cmake compiler cuda_toolkit)"
    assert_contains "$preview" "apt-get update"
    assert_contains "$preview" "apt-get install -y git cmake build-essential nvidia-cuda-toolkit"
}

test_state_and_shell_split_helpers() {
    local tmp
    local parsed
    local timestamp_value

    tmp="$(mktemp -d)"
    mkdir -p "$tmp/state/llama-server"

    # shellcheck disable=SC1090
    source "$BIN"
    STATE_FILE="$tmp/state/llama-server/current.env"

    write_state "demo" "/tmp/My Models/model.gguf" "1234" "8192" "999" "128" "16" "1" "cuda0"
    assert_contains "$(cmd_arg_from_pid 1234 -m || true)" "/tmp/My Models/model.gguf"
    assert_contains "$(cmd_arg_from_pid 1234 --threads || true)" "16"

    parsed="$(split_shell_words "--mmproj '/tmp/My Models/mmproj.gguf' --flag value" | tr '\0' '\n')"
    assert_contains "$parsed" "--mmproj"
    assert_contains "$parsed" "/tmp/My Models/mmproj.gguf"
    assert_contains "$parsed" "--flag"

    timestamp_value="$(iso_timestamp)"
    assert_contains "$timestamp_value" "T"
}

test_web_round_trip_for_quoted_values() {
    local output

    output="$(
        python3 - <<PY
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import tempfile

spec = spec_from_file_location("llama_web_app", "$ROOT_DIR/web/app.py")
module = module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
manager = module.Manager(Path("$ROOT_DIR/web"))

with tempfile.TemporaryDirectory() as tmp:
    defaults = Path(tmp) / "defaults.env"
    defaults.write_text("LLAMA_SERVER_EXTRA_ARGS='--jinja --chat-template llama3'\\n", encoding="utf-8")
    parsed = manager.parse_env_file(defaults)
    print(parsed["LLAMA_SERVER_EXTRA_ARGS"])

split = manager.split_extra("--mmproj '/tmp/My Models/mmproj.gguf' --flag 'two words'")
print(split["mmproj"])
print(split["extra_args"])
print(manager.build_extra("/tmp/My Models/mmproj.gguf", "--flag 'two words'"))
PY
    )"

    assert_contains "$output" "--jinja --chat-template llama3"
    assert_contains "$output" "/tmp/My Models/mmproj.gguf"
    assert_contains "$output" "--flag 'two words'"
    assert_contains "$output" "--mmproj '/tmp/My Models/mmproj.gguf'"
}

test_quoted_home_paths_from_saved_defaults_expand() {
    local tmp
    local output

    tmp="$(mktemp -d)"
    make_env "$tmp"
    cat >"$tmp/config/llama-server/defaults.env" <<'EOF'
LLAMA_SERVER_LOG='$HOME/models/llama-server.log'
CLAUDE_GATEWAY_LOG='$HOME/models/claude-gateway.log'
GLYPHOS_CONFIG_FILE='$HOME/.glyphos/config.yaml'
EOF

    output="$(
        HOME="$tmp/home" \
        XDG_CONFIG_HOME="$tmp/config" \
        XDG_STATE_HOME="$tmp/state" \
        LLAMA_SERVER_RUNTIME_DIR="$tmp/runtime" \
        bash -c 'source "$1"; printf "%s\n%s\n%s\n" "$LLAMA_SERVER_LOG" "$CLAUDE_GATEWAY_LOG" "$GLYPHOS_CONFIG_FILE"' _ "$BIN"
    )"

    assert_contains "$output" "$tmp/home/models/llama-server.log"
    assert_contains "$output" "$tmp/home/models/claude-gateway.log"
    assert_contains "$output" "$tmp/home/.glyphos/config.yaml"
    assert_not_contains "$output" '$HOME/models/llama-server.log'
}


test_cuda_cc_parsing_rejects_non_numeric_values() {
    # shellcheck disable=SC1090
    source "$BIN"
    if cc_to_int "NVIDIA-SMI failed" >/dev/null 2>&1; then
        fail "expected non-numeric CUDA compute capability to be rejected"
    fi
    LLAMA_HOST_CUDA_CC="NVIDIA-SMI failed"
    if detect_host_cuda_cc >/dev/null 2>&1; then
        fail "expected invalid LLAMA_HOST_CUDA_CC to be ignored"
    fi
}

test_startup_log_classifier_emits_actionable_categories() {
    local tmp
    local output

    tmp="$(mktemp -d)"
    cat >"$tmp/llama-server.log" <<'EOF'
llama_context: n_ctx = 983552
ggml_backend_cuda_buffer_type_alloc_buffer: allocating 30736.00 MiB on device 0: cudaMalloc failed: out of memory
llama_init_from_model: failed to initialize the context: failed to allocate buffer for kv cache
EOF
    # shellcheck disable=SC1090
    source "$BIN"
    output="$(startup_failure_message "$tmp/llama-server.log" 983304)"
    assert_contains "$output" "startup_category: kv-cache-oom"
    assert_contains "$output" "requested_context: 983304"
    assert_contains "$output" "lower context"

    cat >"$tmp/llama-server.log" <<'EOF'
mtmd_init_from_file: error: mismatch between text model (n_embd = 2560) and mmproj (n_embd = 2048)
hint: you may be using wrong mmproj
EOF
    output="$(startup_failure_message "$tmp/llama-server.log" 32768)"
    assert_contains "$output" "startup_category: mmproj-mismatch"
    assert_contains "$output" "matching mmproj"
}

test_add_blocks_obvious_mmproj_family_mismatch() {
    local tmp
    local model
    local wrong_mmproj
    local right_mmproj
    local err
    local output

    tmp="$(mktemp -d)"
    make_env "$tmp"
    model="$tmp/models/Qwen3.5-4B-Q6_K.gguf"
    wrong_mmproj="$tmp/models/mmproj-Qwen3.5-2B-f16.gguf"
    right_mmproj="$tmp/models/mmproj-Qwen3.5-4B-BF16.gguf"
    make_model "$model"
    make_model "$wrong_mmproj"
    make_model "$right_mmproj"

    err="$tmp/add.err"
    if run_cli "$tmp" add qwen4 "$model" --mmproj "$wrong_mmproj" >"$tmp/add.out" 2>"$err"; then
        fail "expected mismatched mmproj add to fail"
    fi
    assert_contains "$(cat "$err")" "mmproj appears to target a different model family"

    output="$(run_cli "$tmp" add qwen4 "$model" --mmproj "$wrong_mmproj" --force-mmproj 2>/dev/null)"
    assert_contains "$output" "added qwen4"

    output="$(run_cli "$tmp" add qwen4 "$model" --mmproj "$right_mmproj")"
    assert_contains "$output" "updated qwen4"
}


test_system_memory_influences_fit_posture() {
    local output

    # shellcheck disable=SC1090
    source "$BIN"
    output="$(autofit_memory_posture 11264 65536)"
    assert_contains "$output" "hybrid-fit"
    output="$(autofit_memory_guidance hybrid-fit)"
    assert_contains "$output" "slower runs"

    output="$(autofit_memory_posture 0 65536)"
    assert_contains "$output" "cpu-fit"
    output="$(autofit_memory_guidance cpu-fit)"
    assert_contains "$output" "much slower"

    output="$(autofit_memory_posture 11264 12000)"
    assert_contains "$output" "no-fit"
}

test_auto_fit_uses_ram_aware_hybrid_gpu_layers() {
    local tmp
    local model
    local output
    local state

    tmp="$(mktemp -d)"
    make_env "$tmp"
    model="$tmp/models/qwen4.gguf"
    make_model "$model"
    : >"$tmp/llama-server.log"

    # shellcheck disable=SC1090
    source "$BIN"
    probe_server_binary() {
        SELECTED_LLAMA_SERVER_BIN="/bin/true"
        SELECTED_LLAMA_SERVER_BACKEND="cuda"
        SELECTED_LLAMA_SERVER_SOURCE="test"
        SELECTED_LLAMA_SERVER_STATUS="compatible"
        return 0
    }
    validate_mmproj_for_model() { return 0; }
    detect_gpu_total_mib() { printf '11264\n'; }
    detect_system_available_mib() { printf '65536\n'; }
    llama_server_process_rows() { printf 'pid=1491 port=8080 context=131072 ngl=99 model=/models/gemma.gguf\n'; }
    setsid() { return 0; }
    wait_for_health() { return 0; }
    write_state() { printf 'context=%s ngl=%s parallel=%s\n' "$4" "$5" "$8" >"$tmp/state.out"; }

    LLAMA_SERVER_HOST="127.0.0.1"
    LLAMA_SERVER_PORT="19081"
    LLAMA_SERVER_LOG="$tmp/llama-server.log"
    LLAMA_SERVER_CONTEXT="128000"
    LLAMA_SERVER_NGL="999"
    LLAMA_SERVER_BATCH="128"
    LLAMA_SERVER_THREADS="16"
    LLAMA_SERVER_PARALLEL="auto"
    LLAMA_SERVER_DEVICE="cuda0"
    LLAMA_MODEL_AUTO_FIT="1"
    LLAMA_MODEL_SYNC_OPENCODE="0"
    LLAMA_MODEL_SYNC_CLAUDE="0"
    LLAMA_MODEL_SYNC_OPENCLAW="0"
    LLAMA_MODEL_SYNC_GLYPHOS="0"

    output="$(start_server demo "$model" "" "128000" "999" "128" "16" "auto" "cuda0")"
    state="$(cat "$tmp/state.out")"
    assert_contains "$output" "auto_fit_posture: hybrid-fit"
    assert_contains "$output" "auto_fit_tradeoff: Hybrid-fit: VRAM is tight but system RAM is available"
    assert_contains "$output" "GPU layers 999 -> 24"
    assert_contains "$output" "expect slower runs than full GPU offload"
    assert_contains "$state" "context=32768"
    assert_contains "$state" "ngl=24"
    assert_contains "$state" "parallel=1"
}


test_install_next_steps_sanitize_home_paths() {
    local tmp
    local output
    local next_steps

    tmp="$(mktemp -d)"
    mkdir -p "$tmp/home/Desktop"

    output="$(env \
        HOME="$tmp/home" \
        bash "$ROOT_DIR/install.sh")"
    next_steps="$(printf '%s\n' "$output" | grep -E '^[[:space:]]+(4|11|12)\.')"

    assert_contains "$next_steps" 'Edit ~/.config/llama-server/defaults.env if needed'
    assert_contains "$next_steps" 'Bundled public GlyphOS AI Compute package: ~/.local/share/llama-model-manager/integrations/public-glyphos-ai-compute'
    assert_contains "$next_steps" 'GGML_CUDA_ENABLE_UNIFIED_MEMORY=1 in ~/.config/llama-server/defaults.env'
    assert_not_contains "$next_steps" "$tmp/home"
}


test_install_reports_unified_memory_upgrade_note_for_existing_defaults() {
    local tmp
    local output

    tmp="$(mktemp -d)"
    mkdir -p "$tmp/home/Desktop" "$tmp/config/llama-server" "$tmp/data"
    cat >"$tmp/config/llama-server/defaults.env" <<'EOF'
LLAMA_SERVER_CONTEXT=128000
LLAMA_SERVER_PARALLEL=1
EOF

    output="$(env \
        HOME="$tmp/home" \
        XDG_CONFIG_HOME="$tmp/config" \
        XDG_DATA_HOME="$tmp/data" \
        bash "$ROOT_DIR/install.sh")"

    assert_contains "$output" "existing defaults.env does not include the experimental CUDA unified-memory toggle"
    assert_contains "$output" "GGML_CUDA_ENABLE_UNIFIED_MEMORY=1"
    assert_contains "$output" "should usually be paired with LLAMA_SERVER_PARALLEL=1"
}

test_cuda_unified_memory_preserves_requested_context_and_exports_env() {
    local tmp
    local model
    local output
    local state
    local env_value

    tmp="$(mktemp -d)"
    make_env "$tmp"
    model="$tmp/models/qwen27b.gguf"
    make_model "$model"
    : >"$tmp/llama-server.log"

    # shellcheck disable=SC1090
    source "$BIN"
    probe_server_binary() {
        SELECTED_LLAMA_SERVER_BIN="/bin/true"
        SELECTED_LLAMA_SERVER_BACKEND="cuda"
        SELECTED_LLAMA_SERVER_SOURCE="test"
        SELECTED_LLAMA_SERVER_STATUS="compatible"
        return 0
    }
    validate_mmproj_for_model() { return 0; }
    detect_gpu_total_mib() { printf '24576\n'; }
    detect_system_available_mib() { printf '112640\n'; }
    llama_server_process_rows() { return 0; }
    env() {
        while (($#)) && [[ "$1" == *=* ]]; do
            export "$1"
            shift
        done
        "$@"
    }
    setsid() {
        printf '%s\n' "${GGML_CUDA_ENABLE_UNIFIED_MEMORY:-}" >"$tmp/unified-memory.env"
        return 0
    }
    wait_for_health() { return 0; }
    write_state() { printf 'context=%s parallel=%s unified=%s override=%s\n' "$4" "$8" "${10}" "${11}" >"$tmp/state.out"; }

    LLAMA_SERVER_HOST="127.0.0.1"
    LLAMA_SERVER_PORT="19081"
    LLAMA_SERVER_LOG="$tmp/llama-server.log"
    LLAMA_SERVER_CONTEXT="128000"
    LLAMA_SERVER_NGL="999"
    LLAMA_SERVER_BATCH="128"
    LLAMA_SERVER_THREADS="16"
    LLAMA_SERVER_PARALLEL="auto"
    LLAMA_SERVER_DEVICE="cuda0"
    LLAMA_MODEL_AUTO_FIT="1"
    LLAMA_MODEL_SYNC_OPENCODE="0"
    LLAMA_MODEL_SYNC_CLAUDE="0"
    LLAMA_MODEL_SYNC_OPENCLAW="0"
    LLAMA_MODEL_SYNC_GLYPHOS="0"
    GGML_CUDA_ENABLE_UNIFIED_MEMORY="1"

    output="$(start_server demo "$model" "" "128000" "999" "128" "16" "auto" "cuda0")"
    state="$(cat "$tmp/state.out")"
    env_value="$(cat "$tmp/unified-memory.env")"

    assert_contains "$output" "preflight_status: unified-memory-risk"
    assert_contains "$output" "recommended_context: 65536"
    assert_contains "$output" "performance_warning: CUDA unified memory may be substantially slower on discrete GPUs"
    assert_not_contains "$output" "context 128000 -> 65536"
    assert_contains "$state" "context=128000"
    assert_contains "$state" "parallel=1"
    assert_contains "$state" "unified=enabled"
    assert_contains "$state" "override=unified-memory"
    assert_contains "$env_value" "1"
}

test_current_and_doctor_report_cuda_unified_memory() {
    local tmp
    local current_output
    local doctor_output

    tmp="$(mktemp -d)"
    make_env "$tmp"
    : >"$tmp/llama-server.log"

    # shellcheck disable=SC1090
    source "$BIN"
    HOME="$tmp/home"
    XDG_CONFIG_HOME="$tmp/config"
    XDG_STATE_HOME="$tmp/state"
    STATE_FILE="$tmp/state/current.env"
    LLAMA_SERVER_RUNTIME_DIR="$tmp/runtime"
    LLAMA_SERVER_PORT=19081
    LLAMA_SERVER_LOG="$tmp/llama-server.log"
    GGML_CUDA_ENABLE_UNIFIED_MEMORY="1"
    cat >"$STATE_FILE" <<EOF
CURRENT_PID=$$
CURRENT_CUDA_UNIFIED_MEMORY=enabled
CURRENT_AUTO_FIT_OVERRIDE_REASON=unified-memory
EOF
    find_pid() { printf '%s\n' "$$"; }
    lookup_alias_for_path() { printf 'demo\n'; }
    active_parallel_value() { printf '1\n'; }
    active_mode_name() { printf 'single-client\n'; }
    cmd_arg_from_pid() {
        case "$2" in
            -m) printf '%s\n' '/models/demo.gguf' ;;
            -c) printf '128000\n' ;;
            -ngl) printf '999\n' ;;
            -b) printf '128\n' ;;
            --threads) printf '16\n' ;;
            --device) printf 'cuda0\n' ;;
            *) return 1 ;;
        esac
    }
    curl() { return 0; }
    probe_server_binary() { return 1; }
    gpu_memory_report() { printf 'NVIDIA RTX: 14.3 GiB used / 24.0 GiB total (9.7 GiB free)\n'; }
    system_memory_report() { printf 'RAM: 96.0 GiB available / 110.0 GiB total\n'; }
    detect_gpu_total_mib() { printf '24576\n'; }
    detect_system_available_mib() { printf '98304\n'; }
    llama_server_process_rows() { return 0; }

    current_output="$(show_current)"
    doctor_output="$(show_doctor)"

    assert_contains "$current_output" "cuda_unified_memory: enabled"
    assert_contains "$current_output" "auto_fit_override_reason: unified-memory"
    assert_contains "$doctor_output" "cuda_unified_memory: enabled"
    assert_contains "$doctor_output" "auto_fit_override_reason: unified-memory"
}

test_doctor_reports_gpu_pressure_and_process_rows() {
    local tmp
    local output

    tmp="$(mktemp -d)"
    make_env "$tmp"
    : >"$tmp/llama-server.log"

    # shellcheck disable=SC1090
    source "$BIN"
    find_pid() { return 1; }
    probe_server_binary() { return 1; }
    gpu_memory_report() { printf 'NVIDIA GTX 1080 Ti: 6.3 GiB used / 11.0 GiB total (4.6 GiB free)\n'; }
    system_memory_report() { printf 'RAM: 48.0 GiB available / 64.0 GiB total\n'; }
    detect_gpu_total_mib() { printf '11264\n'; }
    detect_system_available_mib() { printf '49152\n'; }
    llama_server_process_rows() { printf 'pid=1491 port=8080 context=131072 ngl=99 model=/models/gemma.gguf\n'; }

    HOME="$tmp/home"
    XDG_CONFIG_HOME="$tmp/config"
    XDG_STATE_HOME="$tmp/state"
    LLAMA_SERVER_RUNTIME_DIR="$tmp/runtime"
    LLAMA_SERVER_PORT=19081
    LLAMA_SERVER_LOG="$tmp/llama-server.log"

    output="$(show_doctor)"
    assert_contains "$output" "gpu_memory: NVIDIA GTX 1080 Ti"
    assert_contains "$output" "system_memory: RAM: 48.0 GiB available / 64.0 GiB total"
    assert_contains "$output" "fit_posture: hybrid-fit"
    assert_contains "$output" "fit_guidance: Hybrid-fit: VRAM is tight but system RAM is available"
    assert_contains "$output" "gpu_process_count: 1"
    assert_contains "$output" "pid=1491 port=8080 context=131072 ngl=99 model=/models/gemma.gguf"
}

test_registry_parsing_preserves_empty_columns() {
    local tmp
    local output

    tmp="$(mktemp -d)"
    mkdir -p "$tmp/home" "$tmp/config/llama-server" "$tmp/state"
    cat >"$tmp/config/llama-server/models.tsv" <<'EOF'
# alias<TAB>model_path<TAB>extra_args<TAB>context<TAB>ngl<TAB>batch<TAB>threads<TAB>parallel<TAB>device<TAB>notes
demo	/tmp/demo.gguf		32000
EOF
    : >"/tmp/demo.gguf"

    output="$(env \
        HOME="$tmp/home" \
        XDG_CONFIG_HOME="$tmp/config" \
        XDG_STATE_HOME="$tmp/state" \
        "$BIN" show demo)"

    assert_contains "$output" "extra_args: "
    assert_contains "$output" "context: 32000"
    assert_not_contains "$output" "extra_args: 32000"
}

test_doctor_tolerates_missing_log_markers() {
    local tmp
    local output

    tmp="$(mktemp -d)"
    mkdir -p "$tmp/home" "$tmp/config/llama-server" "$tmp/state" "$tmp/runtime"
    cat >"$tmp/config/llama-server/defaults.env" <<EOF
LLAMA_SERVER_BIN=
LLAMA_SERVER_DEVICE=
LLAMA_SERVER_PORT=19081
LLAMA_SERVER_LOG=$tmp/llama-server.log
EOF
    : >"$tmp/llama-server.log"

    output="$(env \
        HOME="$tmp/home" \
        PATH="/usr/bin:/bin" \
        XDG_CONFIG_HOME="$tmp/config" \
        XDG_STATE_HOME="$tmp/state" \
        LLAMA_SERVER_RUNTIME_DIR="$tmp/runtime" \
        "$BIN" doctor)"

    assert_contains "$output" "health: unavailable"
    assert_contains "$output" "binary_status: unavailable"
}

test_doctor_reports_install_health() {
    local tmp
    local output
    local api_pid
    local api_port_file
    local api_port

    tmp="$(mktemp -d)"
    make_env "$tmp"

    output="$(LLAMA_MODEL_WEB_PORT=9 run_doctor "$tmp")"
    assert_contains "$output" "installed_web_launcher: no"
    assert_contains "$output" "installed_web_app: no"
    assert_contains "$output" "bundled_glyphos_integration: no"
    assert_contains "$output" "context_mode_mcp_installed: no"
    assert_contains "$output" "install_ok: no"
    assert_contains "$output" "install_guidance: Run ./install.sh"

    mkdir -p "$tmp/home/.local/bin" \
        "$tmp/home/.local/share/llama-model-manager/web" \
        "$tmp/home/.local/share/llama-model-manager/integrations/public-glyphos-ai-compute/glyphos_ai" \
        "$tmp/home/.local/share/llama-model-manager/integrations/context-mode-mcp"
    : >"$tmp/home/.local/bin/llama-model-web"
    chmod +x "$tmp/home/.local/bin/llama-model-web"
    : >"$tmp/home/.local/share/llama-model-manager/web/app.py"
    : >"$tmp/home/.local/share/llama-model-manager/integrations/context-mode-mcp/package.json"

    output="$(LLAMA_MODEL_WEB_PORT=9 run_doctor "$tmp")"
    assert_contains "$output" "installed_web_launcher: yes"
    assert_contains "$output" "installed_web_app: yes"
    assert_contains "$output" "bundled_glyphos_integration: yes"
    assert_contains "$output" "context_mode_mcp_installed: yes"
    assert_contains "$output" "install_ok: yes"
    assert_contains "$output" "dashboard_api_reachable: no"

    api_port_file="$tmp/dashboard-api.port"
    python3 - "$api_port_file" <<'PY' &
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import sys

port_file = sys.argv[1]

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/api/state":
            self.send_response(404)
            self.end_headers()
            return
        payload = json.dumps({
            "glyphos_config_exists": True,
            "glyphos_telemetry": {"available": False, "routing": {}},
            "context_glyphos_pipeline": {"status": "activation_pending"},
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        return

server = HTTPServer(("127.0.0.1", 0), Handler)
with open(port_file, "w", encoding="utf-8") as handle:
    handle.write(str(server.server_port))
server.serve_forever()
PY
    api_pid=$!
    for _ in $(seq 1 50); do
        [[ -s "$api_port_file" ]] && break
        sleep 0.05
    done
    api_port="$(cat "$api_port_file")"
    output="$(LLAMA_MODEL_WEB_PORT="$api_port" run_doctor "$tmp")"
    kill "$api_pid" 2>/dev/null || true
    wait "$api_pid" 2>/dev/null || true

    assert_contains "$output" "dashboard_api_reachable: yes"
    assert_contains "$output" "dashboard_api_glyphos_telemetry: no"
    assert_contains "$output" "dashboard_api_context_glyphos_status: activation_pending"
    assert_contains "$output" "dashboard_api_glyphos_config: yes"
    assert_contains "$output" "dashboard_api_guidance: Live dashboard cannot see bundled GlyphOS"
}

test_dashboard_service_unit_rendering() {
    local unit

    # shellcheck disable=SC1090
    source "$BIN"
    unit="$(dashboard_service_unit_text)"
    assert_contains "$unit" "Description=LLM Model Manager Dashboard"
    assert_contains "$unit" "ExecStart=%h/.local/bin/llama-model-web --no-browser --require-bind --host 127.0.0.1 --port 8765"
    assert_contains "$unit" "Environment=LLAMA_MODEL_WEB_SERVICE=1"
    assert_contains "$unit" "Restart=on-failure"
    assert_contains "$unit" "WantedBy=default.target"
}

test_dashboard_service_status_reports_unsupported_without_systemctl() {
    local tmp
    local output

    tmp="$(mktemp -d)"
    output="$(env \
        HOME="$tmp/home" \
        XDG_CONFIG_HOME="$tmp/config" \
        XDG_STATE_HOME="$tmp/state" \
        LLAMA_MODEL_SYSTEMCTL_BIN="$tmp/not-a-real-systemctl" \
        "$BIN" dashboard-service status)"

    assert_contains "$output" "supported: no"
    assert_contains "$output" "status: unavailable"
}

test_doctor_reports_external_systemd_owner() {
    local tmp
    local output

    tmp="$(mktemp -d)"
    mkdir -p "$tmp/home" "$tmp/config/llama-server" "$tmp/state" "$tmp/runtime"
    cat >"$tmp/config/llama-server/defaults.env" <<EOF
LLAMA_SERVER_BIN=
LLAMA_SERVER_DEVICE=
LLAMA_SERVER_PORT=19081
LLAMA_SERVER_LOG=$tmp/llama-server.log
EOF
    : >"$tmp/llama-server.log"

    # shellcheck disable=SC1090
    source "$BIN"
    find_pid() { printf '%s\n' "$$"; }
    pid_cgroup_text() { printf '0::/system.slice/llama-terran.service\n'; }
    probe_server_binary() { return 1; }

    HOME="$tmp/home"
    XDG_CONFIG_HOME="$tmp/config"
    XDG_STATE_HOME="$tmp/state"
    STATE_FILE="$tmp/state/current.env"
    LLAMA_SERVER_RUNTIME_DIR="$tmp/runtime"
    LLAMA_SERVER_PORT=19081
    LLAMA_SERVER_LOG="$tmp/llama-server.log"

    output="$(show_doctor)"

    assert_contains "$output" "external_owner: yes"
    assert_contains "$output" "external_owner_unit: llama-terran.service"
    assert_contains "$output" "external_owner_message: external systemd service appears to own port 19081; stop/disable llama-terran.service or move one side to a different port"
}


test_sync_opencode_updates_config_and_state() {
    local tmp
    local output
    local config
    local state_json

    tmp="$(mktemp -d)"
    make_env "$tmp"
    mkdir -p "$tmp/models" "$tmp/config/opencode" "$tmp/state/opencode"
    : >"$tmp/models/Qwen3.5-9B-Q8_0.gguf"
    cat >"$tmp/config/llama-server/models.tsv" <<EOF
# alias<TAB>model_path<TAB>extra_args<TAB>context<TAB>ngl<TAB>batch<TAB>threads<TAB>parallel<TAB>device<TAB>notes
qwen35-9b-q8	$tmp/models/Qwen3.5-9B-Q8_0.gguf		65536
EOF
    cat >"$tmp/config/opencode/opencode.json" <<'EOF'
{
  "provider": {
    "other": {
      "name": "keep-me"
    }
  },
  "permissions": {
    "fs": "read-only"
  }
}
EOF
    cat >"$tmp/state/opencode/model.json" <<'EOF'
{
  "providerID": "llamacpp",
  "modelID": "old.gguf",
  "id": "llamacpp/old.gguf",
  "provider": "llamacpp",
  "recent": ["llamacpp/old.gguf", "other/model"],
  "variant": {
    "llamacpp/old.gguf": "default"
  },
  "favorite": {
    "keep": true
  }
}
EOF

    output="$(run_cli "$tmp" sync-opencode --preset balanced qwen35-9b-q8)"
    assert_contains "$output" "status: synced"
    assert_contains "$output" "preset: balanced"
    assert_contains "$output" "opencode_model: llamacpp/Qwen3.5-9B-Q8_0.gguf"
    assert_contains "$output" "timeout_ms: 1800000"
    assert_contains "$output" "chunk_timeout_ms: 60000"

    config="$(cat "$tmp/config/opencode/opencode.json")"
    state_json="$(cat "$tmp/state/opencode/model.json")"
    assert_contains "$config" '"model": "llamacpp/Qwen3.5-9B-Q8_0.gguf"'
    assert_contains "$config" '"baseURL": "http://127.0.0.1:19081/v1"'
    assert_contains "$config" '"timeout": 1800000'
    assert_contains "$config" '"chunkTimeout": 60000'
    assert_contains "$config" '"other"'
    assert_contains "$state_json" '"providerID": "llamacpp"'
    assert_contains "$state_json" '"modelID": "Qwen3.5-9B-Q8_0.gguf"'
    assert_contains "$state_json" '"id": "llamacpp/Qwen3.5-9B-Q8_0.gguf"'
    assert_contains "$state_json" '"llamacpp/Qwen3.5-9B-Q8_0.gguf"'
    assert_contains "$state_json" '"favorite"'
}

test_sync_opencode_long_run_preset() {
    local tmp
    local output
    local config

    tmp="$(mktemp -d)"
    make_env "$tmp"
    mkdir -p "$tmp/models" "$tmp/config/opencode" "$tmp/state/opencode"
    : >"$tmp/models/Qwen3.5-9B-Q8_0.gguf"
    cat >"$tmp/config/llama-server/models.tsv" <<EOF
# alias<TAB>model_path<TAB>extra_args<TAB>context<TAB>ngl<TAB>batch<TAB>threads<TAB>parallel<TAB>device<TAB>notes
qwen35-9b-q8	$tmp/models/Qwen3.5-9B-Q8_0.gguf		65536
EOF

    output="$(run_cli "$tmp" sync-opencode --preset long-run qwen35-9b-q8)"
    assert_contains "$output" "preset: long-run"
    assert_contains "$output" "timeout_ms: 7200000"
    assert_contains "$output" "chunk_timeout_ms: 300000"
    assert_contains "$output" "runtime_note: single-client recommended for long local reasoning sessions"

    config="$(cat "$tmp/config/opencode/opencode.json")"
    assert_contains "$config" '"timeout": 7200000'
    assert_contains "$config" '"chunkTimeout": 300000'
}

test_switch_auto_syncs_opencode_by_default() {
    local tmp
    local model
    local output
    local config
    local state_json

    tmp="$(mktemp -d)"
    make_env "$tmp"
    mkdir -p "$tmp/models" "$tmp/config/opencode" "$tmp/state/opencode" "$tmp/state/llama-server"
    model="$tmp/models/Qwen3.5-4B-Q6_K.gguf"
    make_model "$model"
    : >"$tmp/llama-server.log"

    # shellcheck disable=SC1090
    source "$BIN"
    probe_server_binary() {
        SELECTED_LLAMA_SERVER_BIN="/bin/true"
        SELECTED_LLAMA_SERVER_BACKEND="cpu"
        SELECTED_LLAMA_SERVER_SOURCE="test"
        SELECTED_LLAMA_SERVER_STATUS="compatible"
        return 0
    }
    validate_mmproj_for_model() { return 0; }
    setsid() { return 0; }
    wait_for_health() { return 0; }
    find_pid() { return 1; }

    APP_ROOT="$ROOT_DIR"
    HOME="$tmp/home"
    XDG_CONFIG_HOME="$tmp/config"
    XDG_STATE_HOME="$tmp/state"
    STATE_FILE="$tmp/state/llama-server/current.env"
    OPENCODE_CONFIG_FILE="$tmp/config/opencode/opencode.json"
    OPENCODE_MODEL_STATE_FILE="$tmp/state/opencode/model.json"
    LLAMA_SERVER_HOST="127.0.0.1"
    LLAMA_SERVER_PORT="19081"
    LLAMA_SERVER_LOG="$tmp/llama-server.log"
    LLAMA_SERVER_CONTEXT="32768"
    LLAMA_SERVER_NGL="0"
    LLAMA_SERVER_BATCH="128"
    LLAMA_SERVER_THREADS="16"
    LLAMA_SERVER_PARALLEL="1"
    LLAMA_SERVER_DEVICE=""
    LLAMA_MODEL_AUTO_FIT="1"
    LLAMA_MODEL_SYNC_OPENCODE="1"
    LLAMA_MODEL_SYNC_CLAUDE="0"
    LLAMA_MODEL_SYNC_OPENCLAW="0"
    LLAMA_MODEL_SYNC_GLYPHOS="0"

    output="$(start_server qwen4 "$model" "" "32768" "0" "128" "16" "1" "")"
    assert_contains "$output" "synced_opencode_model: llamacpp/Qwen3.5-4B-Q6_K.gguf"
    assert_contains "$output" "opencode_reload_note: restart or reload OpenCode"
    assert_contains "$output" "skipped_claude_sync: disabled"
    assert_contains "$output" "started qwen4 on port 19081"

    config="$(cat "$OPENCODE_CONFIG_FILE")"
    state_json="$(cat "$OPENCODE_MODEL_STATE_FILE")"
    assert_contains "$config" '"model": "llamacpp/Qwen3.5-4B-Q6_K.gguf"'
    assert_contains "$config" '"Qwen3.5-4B-Q6_K.gguf"'
    assert_contains "$config" '"baseURL": "http://127.0.0.1:19081/v1"'
    assert_contains "$state_json" '"llamacpp/Qwen3.5-4B-Q6_K.gguf"'
}

test_switch_skips_opencode_when_auto_sync_disabled() {
    local tmp
    local model
    local output

    tmp="$(mktemp -d)"
    make_env "$tmp"
    mkdir -p "$tmp/models" "$tmp/config/opencode" "$tmp/state/opencode" "$tmp/state/llama-server"
    model="$tmp/models/Qwen3.5-4B-Q6_K.gguf"
    make_model "$model"
    : >"$tmp/llama-server.log"

    # shellcheck disable=SC1090
    source "$BIN"
    probe_server_binary() {
        SELECTED_LLAMA_SERVER_BIN="/bin/true"
        SELECTED_LLAMA_SERVER_BACKEND="cpu"
        SELECTED_LLAMA_SERVER_SOURCE="test"
        SELECTED_LLAMA_SERVER_STATUS="compatible"
        return 0
    }
    validate_mmproj_for_model() { return 0; }
    setsid() { return 0; }
    wait_for_health() { return 0; }
    find_pid() { return 1; }

    APP_ROOT="$ROOT_DIR"
    STATE_FILE="$tmp/state/llama-server/current.env"
    OPENCODE_CONFIG_FILE="$tmp/config/opencode/opencode.json"
    OPENCODE_MODEL_STATE_FILE="$tmp/state/opencode/model.json"
    LLAMA_SERVER_HOST="127.0.0.1"
    LLAMA_SERVER_PORT="19081"
    LLAMA_SERVER_LOG="$tmp/llama-server.log"
    LLAMA_SERVER_CONTEXT="32768"
    LLAMA_SERVER_NGL="0"
    LLAMA_SERVER_BATCH="128"
    LLAMA_SERVER_THREADS="16"
    LLAMA_SERVER_PARALLEL="1"
    LLAMA_SERVER_DEVICE=""
    LLAMA_MODEL_SYNC_OPENCODE="0"
    LLAMA_MODEL_SYNC_CLAUDE="0"
    LLAMA_MODEL_SYNC_OPENCLAW="0"
    LLAMA_MODEL_SYNC_GLYPHOS="0"

    output="$(start_server qwen4 "$model" "" "32768" "0" "128" "16" "1" "")"
    assert_contains "$output" "skipped_opencode_sync: disabled"
    assert_not_contains "$output" "synced_opencode_model:"
    [[ ! -e "$OPENCODE_CONFIG_FILE" ]] || fail "expected disabled OpenCode sync not to create config"
}

test_switch_opencode_sync_failure_is_non_fatal() {
    local tmp
    local model
    local output

    tmp="$(mktemp -d)"
    make_env "$tmp"
    mkdir -p "$tmp/models" "$tmp/config/opencode" "$tmp/state/opencode" "$tmp/state/llama-server"
    model="$tmp/models/Qwen3.5-4B-Q6_K.gguf"
    make_model "$model"
    : >"$tmp/llama-server.log"
    printf '%s\n' '{ invalid json' >"$tmp/config/opencode/opencode.json"

    # shellcheck disable=SC1090
    source "$BIN"
    probe_server_binary() {
        SELECTED_LLAMA_SERVER_BIN="/bin/true"
        SELECTED_LLAMA_SERVER_BACKEND="cpu"
        SELECTED_LLAMA_SERVER_SOURCE="test"
        SELECTED_LLAMA_SERVER_STATUS="compatible"
        return 0
    }
    validate_mmproj_for_model() { return 0; }
    setsid() { return 0; }
    wait_for_health() { return 0; }
    find_pid() { return 1; }

    APP_ROOT="$ROOT_DIR"
    HOME="$tmp/home"
    XDG_CONFIG_HOME="$tmp/config"
    XDG_STATE_HOME="$tmp/state"
    STATE_FILE="$tmp/state/llama-server/current.env"
    OPENCODE_CONFIG_FILE="$tmp/config/opencode/opencode.json"
    OPENCODE_MODEL_STATE_FILE="$tmp/state/opencode/model.json"
    LLAMA_SERVER_HOST="127.0.0.1"
    LLAMA_SERVER_PORT="19081"
    LLAMA_SERVER_LOG="$tmp/llama-server.log"
    LLAMA_SERVER_CONTEXT="32768"
    LLAMA_SERVER_NGL="0"
    LLAMA_SERVER_BATCH="128"
    LLAMA_SERVER_THREADS="16"
    LLAMA_SERVER_PARALLEL="1"
    LLAMA_SERVER_DEVICE=""
    LLAMA_MODEL_SYNC_OPENCODE="1"
    LLAMA_MODEL_SYNC_CLAUDE="0"
    LLAMA_MODEL_SYNC_OPENCLAW="0"
    LLAMA_MODEL_SYNC_GLYPHOS="0"

    output="$(start_server qwen4 "$model" "" "32768" "0" "128" "16" "1" "" 2>&1)"
    assert_contains "$output" "warn_opencode_sync:"
    assert_contains "$output" "invalid JSON"
    assert_contains "$output" "started qwen4 on port 19081"
}

test_sync_openclaw_updates_profile_config() {
    local tmp
    local output
    local config

    tmp="$(mktemp -d)"
    make_env "$tmp"
    mkdir -p "$tmp/models" "$tmp/home/.openclaw-lmm-eval"
    : >"$tmp/models/Qwen3.5-9B-Q8_0.gguf"
    cat >"$tmp/config/llama-server/defaults.env" <<'EOF'
LLAMA_SERVER_BIN=
LLAMA_SERVER_DEVICE=
LLAMA_SERVER_PORT=19081
LLAMA_SERVER_LOG=
OPENCLAW_PROFILE=lmm-eval
OPENCLAW_API_KEY=llama-local
EOF
    cat >"$tmp/config/llama-server/models.tsv" <<EOF
# alias<TAB>model_path<TAB>extra_args<TAB>context<TAB>ngl<TAB>batch<TAB>threads<TAB>parallel<TAB>device<TAB>notes
qwen35-9b-q8	$tmp/models/Qwen3.5-9B-Q8_0.gguf		65536
EOF
    cat >"$tmp/home/.openclaw-lmm-eval/openclaw.json" <<'EOF'
{
  "telemetry": {"enabled": false},
  "models": {"providers": {"ollama": {"baseUrl": "http://127.0.0.1:11434"}}}
}
EOF

    output="$(run_cli "$tmp" sync-openclaw --profile lmm-eval qwen35-9b-q8)"
    assert_contains "$output" "openclaw_model: llamacpp/qwen35-9b-q8"

    config="$(cat "$tmp/home/.openclaw-lmm-eval/openclaw.json")"
    assert_contains "$config" '"primary": "llamacpp/qwen35-9b-q8"'
    assert_contains "$config" '"baseUrl": "http://127.0.0.1:19081/v1"'
    assert_contains "$config" '"apiKey": "llama-local"'
    assert_contains "$config" '"telemetry"'
    assert_contains "$config" '"ollama"'
}

test_bundled_glyphos_public_package_exists() {
    [[ -f "$ROOT_DIR/integrations/public-glyphos-ai-compute/README.md" ]] || fail "expected bundled public GlyphOS README"
    [[ -f "$ROOT_DIR/integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/api_client.py" ]] || fail "expected bundled GlyphOS api_client"
    [[ -f "$ROOT_DIR/integrations/public-glyphos-ai-compute/glyphos_ai/glyph/encoder.py" ]] || fail "expected bundled GlyphOS encoder"
    [[ ! -e "$ROOT_DIR/integrations/public-glyphos-ai-compute/q45_engine" ]] || fail "bundled public GlyphOS package must not include q45_engine"
}

test_integration_sync_cli_glyphos_entrypoint() {
    local tmp
    local config

    tmp="$(mktemp -d)"
    python3 "$ROOT_DIR/scripts/integration_sync.py" glyphos         --config-file "$tmp/config.yaml"         --model-name "Qwen3.5-9B-Q8_0.gguf"         --api-base "http://127.0.0.1:8081/v1"         --timeout-seconds 300 >/dev/null

    config="$(cat "$tmp/config.yaml")"
    assert_contains "$config" 'preferred_local_backend: llamacpp'
    assert_contains "$config" 'url: http://127.0.0.1:8081/v1'
    assert_contains "$config" 'model: Qwen3.5-9B-Q8_0.gguf'
    assert_contains "$config" 'timeout: 300'
}

test_sync_glyphos_updates_config() {
    local tmp
    local output
    local config

    tmp="$(mktemp -d)"
    make_env "$tmp"
    mkdir -p "$tmp/models"
    : >"$tmp/models/Qwen3.5-9B-Q8_0.gguf"
    cat >"$tmp/config/llama-server/models.tsv" <<EOF
# alias<TAB>model_path<TAB>extra_args<TAB>context<TAB>ngl<TAB>batch<TAB>threads<TAB>parallel<TAB>device<TAB>notes
qwen35-9b-q8	$tmp/models/Qwen3.5-9B-Q8_0.gguf		65536
EOF
    mkdir -p "$tmp/home/.glyphos"
    cat >"$tmp/home/.glyphos/config.yaml" <<'EOF'
ai_compute:
  openai:
    enabled: false
logging:
  level: INFO
EOF

    output="$(run_cli "$tmp" sync-glyphos qwen35-9b-q8)"
    assert_contains "$output" "status: synced"
    assert_contains "$output" "glyphos_model: Qwen3.5-9B-Q8_0.gguf"
    assert_contains "$output" "routing_preference: llamacpp"

    config="$(cat "$tmp/home/.glyphos/config.yaml")"
    assert_contains "$config" 'preferred_local_backend: llamacpp'
    assert_contains "$config" 'url: http://127.0.0.1:19081/v1'
    assert_contains "$config" 'model: Qwen3.5-9B-Q8_0.gguf'
    assert_contains "$config" 'timeout: 300'
    assert_contains "$config" 'openai:'
}

test_sync_claude_updates_settings() {
    local tmp
    local output
    local settings

    tmp="$(mktemp -d)"
    make_env "$tmp"
    mkdir -p "$tmp/home/.claude"
    cat >"$tmp/config/llama-server/defaults.env" <<'EOF'
LLAMA_SERVER_BIN=
LLAMA_SERVER_DEVICE=
LLAMA_SERVER_PORT=19081
LLAMA_SERVER_LOG=
CLAUDE_BASE_URL=http://127.0.0.1:4000
CLAUDE_MODEL_ID=qwen35-9b-q8
CLAUDE_AUTH_TOKEN=local-dev-token
EOF
    cat >"$tmp/home/.claude/settings.json" <<'EOF'
{
  "theme": "dark"
}
EOF

    output="$(run_cli "$tmp" sync-claude)"
    assert_contains "$output" "status: synced"
    assert_contains "$output" "claude_api_key: mirrored-from-auth-token"

    settings="$(cat "$tmp/home/.claude/settings.json")"
    assert_contains "$settings" '"model": "qwen35-9b-q8"'
    assert_contains "$settings" '"ANTHROPIC_BASE_URL": "http://127.0.0.1:4000"'
    assert_contains "$settings" '"ANTHROPIC_AUTH_TOKEN": "local-dev-token"'
    assert_contains "$settings" '"ANTHROPIC_API_KEY": "local-dev-token"'
    assert_contains "$settings" '"theme": "dark"'
}

test_claude_gateway_detects_existing_listener() {
    local tmp
    local output

    tmp="$(mktemp -d)"
    make_env "$tmp"

    # shellcheck disable=SC1090
    source "$BIN"
    CLAUDE_GATEWAY_PORT=4000
    CLAUDE_GATEWAY_LOG="$tmp/claude-gateway.log"
    CLAUDE_GATEWAY_PID_FILE="$tmp/claude-gateway.pid"
    claude_gateway_health_ok() { return 0; }
    claude_gateway_pid() { printf '44339\n'; }
    claude_gateway_listener_pid() { printf '28010\n'; }
    pid_matches_claude_gateway() {
        [[ "$1" == '44339' ]] && return 1
        [[ "$1" == '28010' ]]
    }
    claude_gateway_model_id() { printf 'qwen35-9b-q8\n'; }
    claude_gateway_upstream_base() { printf 'http://127.0.0.1:8081/v1\n'; }

    output="$(claude_gateway_start)"
    assert_contains "$output" 'status: running'
    assert_contains "$output" 'pid: 28010'

    output="$(claude_gateway_status)"
    assert_contains "$output" 'running: yes'
    assert_contains "$output" 'pid: 28010'
}

test_claude_gateway_timeout_default_visible() {
    local tmp
    local output

    tmp="$(mktemp -d)"
    make_env "$tmp"
    cat >"$tmp/config/llama-server/defaults.env" <<'EOF'
LLAMA_SERVER_BIN=
LLAMA_SERVER_DEVICE=
LLAMA_SERVER_PORT=19081
LLAMA_SERVER_LOG=
CLAUDE_GATEWAY_UPSTREAM_TIMEOUT_SECONDS=1800
EOF

    output="$(run_cli "$tmp" claude-gateway status)"
    assert_contains "$output" "upstream_timeout_seconds: 1800"
}

test_claude_gateway_status_without_runtime_is_clean() {
    local tmp
    local output

    tmp="$(mktemp -d)"
    make_env "$tmp"
    output="$(run_cli "$tmp" claude-gateway status)"
    assert_contains "$output" "running: no"
    assert_contains "$output" "url: http://127.0.0.1:4000"
}


test_download_lifecycle_cli_fallbacks() {
    local tmp
    local output
    local jobs_file
    local job_id="job123456789"

    tmp="$(mktemp -d)"
    make_env "$tmp"

    output="$(run_cli "$tmp" download-jobs)"
    assert_contains "$output" "no jobs"

    jobs_file="$tmp/state/llama-server/download-jobs.json"
    mkdir -p "$(dirname "$jobs_file")"
    cat >"$jobs_file" <<EOF
{
  "schema_version": 1,
  "updated_at": "",
  "items": [
    {
      "id": "$job_id",
      "status": "running",
      "repo_id": "author/model",
      "artifact_name": "model-Q4_K_M.gguf",
      "destination_root": "$tmp/models",
      "bytes_downloaded": 10,
      "bytes_total": 100,
      "progress": 0.1,
      "cancel_requested": false
    }
  ]
}
EOF

    output="$(run_cli "$tmp" download-jobs)"
    assert_contains "$output" "$job_id"
    assert_contains "$output" "author/model"

    output="$(LLAMA_MODEL_WEB_PORT=9 run_cli "$tmp" download-cancel "$job_id")"
    assert_contains "$output" "id: $job_id"
    assert_contains "$output" "status: cancelled"

    output="$(LLAMA_MODEL_WEB_PORT=9 run_cli "$tmp" download-retry "$job_id")"
    assert_contains "$output" "status: queued"
    assert_contains "$output" "artifact_name: model-Q4_K_M.gguf"
}

main() {
    test_host_match_accepts_bundled_backend
    test_host_mismatch_rejects_bundled_backend
    test_cpu_fallback_selected_when_gpu_bundle_is_rejected
    test_no_safe_binary_path_reports_build_guidance
    test_docs_no_longer_imply_universal_gpu_binary
    test_installers_support_bootstrap_tty_handoff_and_empty_registry_seed
    test_install_migrates_placeholder_seed_registry
    test_install_preserves_real_registry_entries
    test_dependency_install_preview_exists
    test_state_and_shell_split_helpers
    test_quoted_home_paths_from_saved_defaults_expand
    test_web_round_trip_for_quoted_values
    test_cuda_cc_parsing_rejects_non_numeric_values
    test_startup_log_classifier_emits_actionable_categories
    test_add_blocks_obvious_mmproj_family_mismatch
    test_install_next_steps_sanitize_home_paths
    test_install_reports_unified_memory_upgrade_note_for_existing_defaults
    test_system_memory_influences_fit_posture
    test_cuda_unified_memory_preserves_requested_context_and_exports_env
    test_current_and_doctor_report_cuda_unified_memory
    test_auto_fit_uses_ram_aware_hybrid_gpu_layers
    test_doctor_reports_gpu_pressure_and_process_rows
    test_registry_parsing_preserves_empty_columns
    test_doctor_tolerates_missing_log_markers
    test_doctor_reports_install_health
    test_dashboard_service_unit_rendering
    test_dashboard_service_status_reports_unsupported_without_systemctl
    test_doctor_reports_external_systemd_owner
    test_bundled_glyphos_public_package_exists
    test_integration_sync_cli_glyphos_entrypoint
    test_sync_opencode_updates_config_and_state
    test_sync_opencode_long_run_preset
    test_switch_auto_syncs_opencode_by_default
    test_switch_skips_opencode_when_auto_sync_disabled
    test_switch_opencode_sync_failure_is_non_fatal
    test_download_lifecycle_cli_fallbacks
    test_sync_openclaw_updates_profile_config
    test_sync_glyphos_updates_config
    test_sync_claude_updates_settings
    test_claude_gateway_detects_existing_listener
    test_claude_gateway_timeout_default_visible
    test_claude_gateway_status_without_runtime_is_clean
    printf 'All portability tests passed.\n'
}

main "$@"
