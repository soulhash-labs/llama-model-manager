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
    assert_contains "$defaults" "OPENCLAW_PROFILE="
    assert_contains "$defaults" "CLAUDE_GATEWAY_PORT=4000"
    assert_contains "$defaults" "CLAUDE_GATEWAY_UPSTREAM_TIMEOUT_SECONDS=1800"
    assert_not_contains "$defaults" "LLAMA_SERVER_DEVICE=cuda0"
    assert_contains "$web_index" "Claude Gateway Timeout (s)"
    assert_not_contains "$web_index" "GPU-aware defaults"
    assert_contains "$install_script" "Would you like to check/install build dependencies"
    assert_contains "$install_script" "llama-model sync-opencode"
    assert_contains "$install_script" "llama-model sync-openclaw"
    assert_contains "$install_script" "llama-model sync-claude"
    assert_contains "$install_script" "llama-model sync-glyphos"
    assert_contains "$readme" "integrations/public-glyphos-ai-compute/"
    assert_contains "$help" "bundled public copy lives under integrations/public-glyphos-ai-compute/"
    assert_contains "$install_script" "Bundled public GlyphOS AI Compute package"
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
    assert_contains "$models" "# alias<TAB>model_path<TAB>extra_args<TAB>context<TAB>ngl<TAB>batch<TAB>threads<TAB>parallel<TAB>device<TAB>notes"
    assert_not_contains "$models" "qwen36-35b-q2"
    assert_not_contains "$models" "gemma4-e4b-q8"

    app_py="$(cat "$ROOT_DIR/web/app.py")"
    app_js="$(cat "$ROOT_DIR/web/app.js")"
    assert_contains "$app_py" '"home_dir": str(self.home)'
    assert_contains "$app_js" 'function displayPath(path) {'
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
    test_web_round_trip_for_quoted_values
    test_cuda_cc_parsing_rejects_non_numeric_values
    test_startup_log_classifier_emits_actionable_categories
    test_add_blocks_obvious_mmproj_family_mismatch
    test_system_memory_influences_fit_posture
    test_auto_fit_uses_ram_aware_hybrid_gpu_layers
    test_doctor_reports_gpu_pressure_and_process_rows
    test_registry_parsing_preserves_empty_columns
    test_doctor_tolerates_missing_log_markers
    test_dashboard_service_unit_rendering
    test_dashboard_service_status_reports_unsupported_without_systemctl
    test_doctor_reports_external_systemd_owner
    test_bundled_glyphos_public_package_exists
    test_integration_sync_cli_glyphos_entrypoint
    test_sync_opencode_updates_config_and_state
    test_sync_opencode_long_run_preset
    test_sync_openclaw_updates_profile_config
    test_sync_glyphos_updates_config
    test_sync_claude_updates_settings
    test_claude_gateway_detects_existing_listener
    test_claude_gateway_timeout_default_visible
    test_claude_gateway_status_without_runtime_is_clean
    printf 'All portability tests passed.\n'
}

main "$@"
