# Fix: GPU Offload Defaulting to CPU on Fresh Installs

## Problem

On fresh installs of Llama Model Manager, inference ran on **CPU only** even when the host had capable GPUs (CUDA, Vulkan, or Metal). Users saw no warning — the server just started and ran orders of magnitude slower than it should.

This was caused by two independent gaps:

1. **`bin/llama-model` could not detect the backend of external `llama-server` binaries** found on `$PATH`, so auto-fit VRAM checks were skipped and GPU offload was never confirmed.
2. **The installer shipped no `llama-server` binary at all** — the `runtime/` directory referenced in `install.sh` was gitignored and never existed in the repo.

## Root Cause Analysis

### Gap 1: External Binary Backend Detection (`bin/llama-model`)

When `probe_server_binary()` found an external `llama-server` (from `$PATH` or `LLAMA_SERVER_BIN`), it validated platform format and dynamic library resolution, then set:

```
SELECTED_LLAMA_SERVER_SOURCE="external"
SELECTED_LLAMA_SERVER_BACKEND="external"       ← opaque, not a real backend
SELECTED_LLAMA_SERVER_STATUS="external-unvalidated"
```

This caused a **cascade of skipped logic**:

| Block | Condition | What was skipped |
|-------|-----------|------------------|
| CPU override (line ~2784) | `BACKEND == "cpu"` | ✅ correctly NOT triggered |
| Auto-fit VRAM check (line ~2802) | `BACKEND == "cuda" \|\| device == cuda*` | ❌ skipped — `"external" != "cuda"` |
| Device compatibility (line ~2824) | `BACKEND != "external"` | ❌ blocked — was `"external"` |

The result: a CUDA-compiled binary launched with `ngl=999` but **no VRAM-safe capping, no device flag, no diagnostics** — and on some systems llama-server would silently degrade to CPU because it couldn't determine which GPU to target.

### Gap 2: No Packaged Runtime in Installer

The installer contained dead code:

```bash
# install.sh (line ~354)
if [[ -d "$ROOT_DIR/runtime" ]]; then    # ← Always false — runtime/ is gitignored
    cp -a "$ROOT_DIR/runtime" "$APP_SHARE_DIR/runtime"
fi
```

And an interactive-only prompt at the very end:

```bash
# install.sh (line ~437)
if [[ -t 0 && -t 1 ]]; then              # ← Only works in interactive terminals
    read -r reply ...
    build-runtime ...
fi
```

**Non-interactive / CI / script-driven installs** (the common case for automated deployments) never reached the prompt. The user was left with zero `llama-server` binaries and had to discover `build-runtime` through documentation.

## Fix Summary

Two commits, both pushed to `origin/main`:

| Commit | Scope | Lines Changed |
|--------|-------|--------------|
| `2f52be6` | `bin/llama-model` — external binary backend detection + diagnostics | +66 / -9 |
| `0bfaa92` | `install.sh` — auto-build runtime during install | +126 / -8 |

---

## Fix 1: External Binary Backend Detection (`2f52be6`)

### New Function: `detect_external_binary_backend()`

Added to `bin/llama-model` at ~line 1649. Probes the compiled binary for GPU backend linkage:

```bash
detect_external_binary_backend() {
    local binary="$1"
    local info=""
    case "$SELECTED_LLAMA_SERVER_HOST_OS" in
        linux)
            if command_available ldd; then
                info="$(ldd "$binary" 2>&1 || true)"
                if printf '%s' "$info" | grep -qiE 'libcublas|libcudart|libggml_cuda'; then
                    printf 'cuda\n'; return 0
                fi
                if printf '%s' "$info" | grep -qi 'libvulkan'; then
                    printf 'vulkan\n'; return 0
                fi
            fi
            ;;
        darwin)
            if command_available otool; then
                info="$(otool -L "$binary" 2>/dev/null || true)"
                if printf '%s' "$info" | grep -qi 'Metal'; then
                    printf 'metal\n'; return 0
                fi
            fi
            ;;
    esac
    printf 'cpu\n'
}
```

### Changes to `validate_external_binary()`

Now populates `EXTERNAL_VALIDATE_BACKEND`:

```diff
 validate_external_binary() {
     local binary="$1"
     EXTERNAL_VALIDATE_REASON=""
+    EXTERNAL_VALIDATE_BACKEND=""
     [[ -x "$binary" ]] || { ... return 1; }
     binary_platform_matches_host "$binary" || { ... return 1; }
     binary_dynamic_links_resolve "$binary" || { ... return 1; }
+    EXTERNAL_VALIDATE_BACKEND="$(detect_external_binary_backend "$binary")"
     return 0
 }
```

### Changes to `probe_server_binary()`

External binary records now report the **detected backend** instead of `"external"`:

```diff
 if validate_external_binary "$configured_path"; then
+    local ext_backend="${EXTERNAL_VALIDATE_BACKEND:-cpu}"
     select_binary_record \
         "$configured_path" \
         "external" \
-        "external" \
-        "external-unvalidated" \
-        "using external llama-server binary; backend compatibility must be managed by the installer" \
+        "$ext_backend" \
+        "external-detected" \
+        "using external llama-server binary (${ext_backend} backend detected)" \
         "" \
-        "external install"
+        "${ext_backend^} external"
     return 0
 fi
```

Same change applied to the default PATH binary selection block.

### New Warning: CPU Binary on GPU Host

Added to `start_server()` at ~line 2824. Fires when the host has GPU capability but a CPU-only binary was selected:

```bash
if [[ "$SELECTED_LLAMA_SERVER_BACKEND" == "cpu" ]]; then
    if [[ ",$SELECTED_LLAMA_SERVER_HOST_BACKENDS," == *",cuda,"* ]]; then
        printf 'warning: host has CUDA capability but selected llama-server binary is CPU-only; GPU offload will not be used\n' >&2
        printf 'note: run "llama-model build-runtime --backend cuda" or point LLAMA_SERVER_BIN at a CUDA-enabled llama-server\n' >&2
    elif [[ ",$SELECTED_LLAMA_SERVER_HOST_BACKENDS," == *",vulkan,"* ]]; then
        printf 'warning: host has Vulkan capability but selected llama-server binary is CPU-only; GPU offload will not be used\n' >&2
        printf 'note: run "llama-model build-runtime --backend vulkan" or point LLAMA_SERVER_BIN at a Vulkan-enabled llama-server\n' >&2
    fi
    ngl="0"
    device=""
```

### Posture Override: "gpu-unknown-vram"

When `detect_gpu_total_mib()` fails (e.g., `nvidia-smi` not in PATH, driver issues), `autofit_memory_posture` returned `"cpu-fit"` — misleading guidance even when a CUDA binary was correctly selected. Added a new posture class:

```bash
# In start_server(), auto-fit VRAM block:
fit_posture="$(autofit_memory_posture "$gpu_total" "$system_available")"
if [[ -z "$gpu_total" && "$fit_posture" == "cpu-fit" ]]; then
    fit_posture="gpu-unknown-vram"
    fit_guidance="VRAM detection failed (nvidia-smi not available or driver issue); GPU offload will be attempted with default settings. If startup fails, run nvidia-smi to diagnose."
fi
```

Added to `autofit_memory_guidance()`:

```bash
gpu-unknown-vram)
    printf 'GPU-unknown-VRAM: GPU binary selected but VRAM could not be measured; GPU offload will be attempted. If startup fails, check nvidia-smi.\n'
    ;;
```

Same override applied in `show_doctor()` for accurate diagnostics.

### Before / After: External CUDA Binary from PATH

**Before:**
```
SELECTED_LLAMA_SERVER_BACKEND="external"
→ auto-fit VRAM block SKIPPED (condition: BACKEND == "cuda")
→ ngl=999 passed with no VRAM capping
→ llama-server may silently degrade to CPU
→ no diagnostic output
```

**After:**
```
SELECTED_LLAMA_SERVER_BACKEND="cuda"    ← ldd detects libcublas
→ auto-fit VRAM block RUNS
→ VRAM measured → ngl capped appropriately
→ GPU offload active
→ doctor reports "cuda" backend correctly
```

---

## Fix 2: Auto-Build Runtime During Install (`0bfaa92`)

### New Function: `build_runtime_during_install()`

Added to `install.sh` at ~line 67. Runs after binaries are installed and before user-facing output.

#### GPU Detection Logic

Probes the host without invoking the full `llama-model doctor`:

```bash
case "$(uname -s)" in
    Linux)
        if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
            primary_backend="cuda"
        elif ldconfig -p 2>/dev/null | grep -q 'libvulkan\.so'; then
            primary_backend="vulkan"
        fi
        ;;
    Darwin)
        primary_backend="metal"
        ;;
esac
```

#### Interactive vs Non-Interactive Behavior

| Mode | Behavior |
|------|----------|
| **Interactive terminal** (`-t 0 && -t 1`) | Shows detected backend, prompts `[Y/n]` before building |
| **Non-interactive** (CI, pipes, scripts) | Auto-builds GPU runtime if build tools are in PATH; falls back to CPU-only if not; **never blocks** |

Non-interactive guard rails:

```bash
# CUDA without nvcc: don't attempt a build that will fail
elif [[ "$primary_backend" == "cuda" ]] && ! command -v nvcc >/dev/null 2>&1; then
    printf 'post-install: CUDA host detected but nvcc not in PATH; skipping GPU build\n'
    printf 'note: set LMM_AUTO_BUILD_RUNTIME=1 to force, or run manually after installing CUDA toolkit\n'
    primary_backend="cpu"
```

#### Runtime Directory Override

Critical fix: `build-runtime` normally resolves `APP_ROOT` to the source checkout (because `web/` exists there). The installer forces the output to the installed location:

```bash
LLAMA_SERVER_RUNTIME_DIR="${APP_SHARE_DIR}/runtime" \
LLAMA_AUTO_INSTALL_DEPS=1 \
    "$bin" build-runtime --backend "$primary_backend" 2>&1 || true
```

#### Post-Build Verification

```bash
runtime_dir="${APP_SHARE_DIR}/runtime/llama-server"
if [[ -d "$runtime_dir" ]] && find "$runtime_dir" -name 'llama-server' -type f -print -quit 2>/dev/null | grep -q .; then
    printf 'post-install: runtime build completed successfully\n'
    find "$runtime_dir" -name 'llama-server' -type f | while read -r b; do
        printf '  -> %s\n' "$b"
    done
else
    printf 'post-install: runtime build did not produce a binary\n'
    printf 'post-install: run "%s build-runtime --backend auto" manually to retry\n' "$bin"
fi
```

### Install Flow Restructure

The main install body was reorganized with explicit step comments:

```bash
# Step 1: Build bundled llama.cpp runtime for the host.
build_runtime_during_install

# Step 2: Copy any pre-built runtime bundles from source tree (rare:
# developer-built extras). The install build already wrote to $APP_SHARE_DIR/runtime.
if [[ -d "$ROOT_DIR/runtime" ]]; then
    rm -rf "$APP_SHARE_DIR/runtime"
    cp -a "$ROOT_DIR/runtime" "$APP_SHARE_DIR/runtime"
fi
```

### End-of-Script Prompt: Conditional Retry

The old unconditional prompt was replaced with a conditional that only appears if the build failed:

```bash
if [[ -t 0 && -t 1 ]]; then
    if [[ "$has_runtime" != "yes" ]]; then
        printf '\nNo llama.cpp runtime was built during install. Compile one now? [Y/n] '
        ...
    fi
fi
```

### Before / After: Install Flow

**Before:**
```
install.sh → copies binaries, web, scripts, integrations
           → dead runtime copy (runtime/ doesn't exist, gitignored)
           → "Next steps: 3. Build a local runtime if needed: llama-model build-runtime"
           → (terminal only) "Would you like to compile? [Y/n]"
           → user left with NO llama-server binary on non-interactive installs
```

**After:**
```
install.sh → copies binaries, web, scripts, integrations
           → build_runtime_during_install()
              → detects GPU backend (cuda/vulkan/metal/cpu)
              → builds llama-server with cmake + appropriate GGML flags
              → writes to ~/.local/share/llama-model-manager/runtime/llama-server/
              → produces .compat.env manifest for validation
           → "post-install: runtime build completed successfully"
           → "  -> /home/user/.local/share/.../runtime/llama-server/linux-x86_64-cuda/llama-server"
           → "Next steps: 1. Open the dashboard..." (no manual build needed)
```

---

## Files Changed

### `bin/llama-model` (commit `2f52be6`)

| Location | Change |
|----------|--------|
| ~line 1649 | **New function** `detect_external_binary_backend()` — probes `ldd`/`otool` for GPU library linkage |
| ~line 1666 | **Modified** `validate_external_binary()` — sets `EXTERNAL_VALIDATE_BACKEND` |
| Globals | **Added** `EXTERNAL_VALIDATE_BACKEND=""` declaration |
| ~line 1797 | **Modified** `probe_server_binary()` configured-path block — uses detected backend |
| ~line 1815 | **Modified** `probe_server_binary()` default-path block — uses detected backend |
| ~line 2824 | **Modified** `start_server()` CPU override — adds warning when host has GPU but binary is CPU-only |
| ~line 2853 | **Modified** `start_server()` auto-fit block — `"cpu-fit"` → `"gpu-unknown-vram"` when CUDA binary selected but VRAM detection fails |
| ~line 1017 | **Modified** `autofit_memory_guidance()` — adds `gpu-unknown-vram` case |
| ~line 3260 | **Modified** `show_doctor()` — same posture override for accurate diagnostics |

### `install.sh` (commit `0bfaa92`)

| Location | Change |
|----------|--------|
| ~line 67 | **New function** `build_runtime_during_install()` — 96 lines of GPU detection, build orchestration, and verification |
| ~line 453 | **New step** in main install body — calls `build_runtime_during_install` after binaries are installed |
| ~line 545 | **Replaced** end-of-script prompt — now conditional retry only if build failed |

---

## Verification

- ✅ `bash -n bin/llama-model` — syntax valid
- ✅ `bash -n install.sh` — syntax valid
- ✅ All pre-commit hooks pass
- ✅ Pushed to `origin/main`

## Impact

| Scenario | Before | After |
|----------|--------|-------|
| Fresh install with CUDA GPU + CUDA toolkit | No binary, manual build needed | CUDA binary built automatically, GPU offload active |
| Fresh install with CUDA GPU, no toolkit | No binary, user must install toolkit | CPU binary built as fallback, clear diagnostic warning |
| External `llama-server` on `$PATH` (CUDA-compiled) | Backend opaque `"external"`, auto-fit skipped | Backend detected as `"cuda"`, auto-fit VRAM checks run |
| External CPU-only `llama-server` on GPU host | Silent CPU execution, no warning | Warning emitted with fix guidance |
| Non-interactive / CI install | No binary at all | CPU binary built automatically |
| `nvidia-smi` unavailable (container, driver issue) | Misleading "cpu-fit" doctor output | "gpu-unknown-vram" posture with actionable guidance |
