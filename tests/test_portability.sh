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
    assert_contains "$help" "llama-model build-runtime --backend auto"
    assert_not_contains "$defaults" "LLAMA_SERVER_DEVICE=cuda0"
    assert_not_contains "$web_index" "GPU-aware defaults"
    assert_contains "$install_script" "Would you like to check/install build dependencies"
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
    assert_contains "$(cmd_arg_from_pid $$ -m || true)" "/tmp/My Models/model.gguf"
    assert_contains "$(cmd_arg_from_pid $$ --threads || true)" "16"

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

main() {
    test_host_match_accepts_bundled_backend
    test_host_mismatch_rejects_bundled_backend
    test_cpu_fallback_selected_when_gpu_bundle_is_rejected
    test_no_safe_binary_path_reports_build_guidance
    test_docs_no_longer_imply_universal_gpu_binary
    test_dependency_install_preview_exists
    test_state_and_shell_split_helpers
    test_web_round_trip_for_quoted_values
    printf 'All portability tests passed.\n'
}

main "$@"
