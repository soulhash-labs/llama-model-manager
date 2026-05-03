---
phase: 12-runtime-packaging
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - bin/llama-model
autonomous: true
requirements:
  - RUNTIME-01
  - RUNTIME-02
  - RUNTIME-03
user_setup: []

must_haves:
  truths:
    - "build-runtime --backend cuda produces a bundle with all required .so files"
    - "ldd on the bundled binary shows no 'not found' for llama/ggml libraries"
    - "llama-server wrapper script launches the real binary with correct LD_LIBRARY_PATH"
    - "bundle contains: llama-server, llama-server.bin, all lib*.so*, .compat.env"
  artifacts:
    - path: "bin/llama-model"
      provides: "locate_built_runtime_dir(), copy_runtime_bundle_files(), resolve_bundle_payload_binary()"
      exports:
        - "locate_built_runtime_dir"
        - "copy_runtime_bundle_files"
        - "resolve_bundle_payload_binary"
      contains:
        - "build_runtime_backend"
        - "write_bundle_manifest"
    - path: "runtime/llama-server/linux-x86_64-cuda/"
      provides: "Self-contained CUDA runtime bundle"
      contains:
        - "llama-server"
        - "llama-server.bin"
        - "llama-server.compat.env"
        - "libggml*.so*"
        - "libllama*.so*"
  key_links:
    - from: "build_runtime_backend()"
      to: "runtime/llama-server/linux-x86_64-cuda/"
      via: "cmake build → copy_runtime_bundle_files → write wrapper → write_bundle_manifest"
    - from: "copy_runtime_bundle_files()"
      to: "build tree output"
      via: "find -name 'libggml*.so*' -o -name 'libllama*.so*'"
    - from: "llama-server (wrapper)"
      to: "llama-server.bin (payload)"
      via: "exec with LD_LIBRARY_PATH=$SCRIPT_DIR"
---

<objective>
Rewrite build_runtime_backend() to produce self-contained runtime bundles with all shared libraries, not just the bare binary.
</objective>

<execution_context>
@/home/angelo/.config/opencode/get-shit-done/workflows/execute-plan.md
@/home/angelo/.config/opencode/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@bin/llama-model
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add runtime packaging helpers (locate, copy, payload resolution)</name>
  <files>bin/llama-model</files>
  <action>
    Add three new functions after locate_built_llama_server() (~line 2290):

    1. locate_built_runtime_dir(binary) — returns the directory containing the built binary (same as cmake output dir for the binary). Simple: cd dirname, pwd.

    2. copy_runtime_bundle_files(runtime_dir, install_dir) — copies:
       - llama-server binary
       - All .so files matching: libllama*.so*, libmtmd*.so*, libggml*.so*
       Must preserve symlinks (cp -a). Use find with -maxdepth 1 for both regular files and symlinks.

       The globs are intentionally broad (libggml*.so*) to catch any future backend-specific libs like libggml-cuda.so*, libggml-vulkan.so*, etc.

    3. resolve_bundle_payload_binary(binary) — if binary.bin exists as a sibling, return it. Otherwise return the binary itself. This lets validation code inspect the real ELF binary when llama-server is a wrapper script.

    Place these functions between locate_built_llama_server() and build_runtime_backend().
  </action>
  <verify>
    <automated>bash -c 'source bin/llama-model 2>/dev/null; declare -f locate_built_runtime_dir copy_runtime_bundle_files resolve_bundle_payload_binary | wc -l'</automated>
  </verify>
  <done>Three new functions exist and are syntactically valid bash</done>
</task>

<task type="auto">
  <name>Task 2: Rewrite build_runtime_backend() packaging tail to produce self-contained bundle</name>
  <files>bin/llama-model</files>
  <action>
    In build_runtime_backend() (~line 2318-2356), replace the packaging tail:

    CURRENT (to replace):
    ```bash
    binary="$(locate_built_llama_server "$build_dir")"
    [[ -n "$binary" ]] || die "..."
    install -m 0755 "$binary" "$install_dir/llama-server"
    write_bundle_manifest "$install_dir/llama-server" "$backend" "$ref"
    printf 'built %s runtime at %s\n' "$backend" "$install_dir/llama-server"
    ```

    NEW (replacement):
    1. Locate the binary and its runtime directory
    2. rm -rf install_dir, mkdir -p install_dir
    3. Call copy_runtime_bundle_files to copy binary + all .so files
    4. If install_dir/llama-server exists (it will), mv it to llama-server.bin
    5. Write a wrapper script at llama-server:
       ```bash
       #!/usr/bin/env bash
       set -euo pipefail
       SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
       export LD_LIBRARY_PATH="$SCRIPT_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
       exec "$SCRIPT_DIR/llama-server.bin" "$@"
       ```
       chmod 0755
    6. Call write_bundle_manifest pointing at the wrapper (llama-server) — preserves existing discovery logic
    7. Print success message

    The wrapper approach is chosen over patchelf because:
    - No dependency on patchelf being installed
    - Works with colocated shared libraries immediately
    - Avoids platform-specific binary patching as the first fix

    IMPORTANT: write_bundle_manifest calls bundle_manifest_for_binary which inspects the binary. Since the wrapper is a script, it may produce wrong results. After the wrapper is written, call write_bundle_manifest with the .bin path instead, or update the manifest writing to handle wrappers. Check what write_bundle_manifest actually does — if it just writes compat.env metadata (backend, ref, etc.), the wrapper path is fine. If it inspects ELF headers, use the .bin path.
  </action>
  <verify>
    <automated>bash -n bin/llama-model</automated>
  </verify>
  <done>build_runtime_backend() produces self-contained bundle with wrapper + payload + all .so files</done>
</task>

<task type="auto">
  <name>Task 3: Update validation helpers to handle wrapper/payload binaries</name>
  <files>bin/llama-model</files>
  <action>
    Update three functions to resolve the payload binary before inspection:

    1. binary_dynamic_links_resolve(binary) — currently returns success immediately for script/text executables. Change it to:
       - First call resolve_bundle_payload_binary(binary) to get the real ELF path
       - Then run ldd on the payload, not the wrapper
       - For non-bundled binaries (no .bin sibling), behavior unchanged

    2. binary_platform_matches_host(binary) — same pattern: resolve to payload first, then check ELF header.

    3. validate_bundled_binary(binary) — after calling binary_dynamic_links_resolve, add an extra strictness check:
       - Run ldd with controlled env: env -i PATH="$PATH" LD_LIBRARY_PATH="$(dirname "$payload")" ldd "$payload"
       - Parse output for "not found" entries matching libggml* or libllama* or libmtmd*
       - If any found, fail validation with reason listing the missing libs
       - This prevents false positives from host-global library paths masking incomplete bundles

    Also update detect_external_binary_backend() (added in commit 2f52be6) to resolve payload before running ldd, so it inspects the real ELF binary's library linkage rather than the wrapper script.

    These changes ensure that when llama-server is a wrapper script, all validation inspects llama-server.bin (the real ELF binary).
  </action>
  <verify>
    <automated>bash -n bin/llama-model</automated>
  </verify>
  <done>All validation helpers inspect payload binary, not wrapper script</done>
</task>

</tasks>

<verification>
End-to-end test (manual, not automated in this plan):
1. Run: llama-model build-runtime --backend cuda
2. Inspect bundle: ls ~/.local/share/llama-model-manager/runtime/llama-server/linux-x86_64-cuda/
   Expected: llama-server, llama-server.bin, llama-server.compat.env, libggml*.so*, libllama*.so*, libmtmd*.so*
3. Run: lldd ~/.local/share/.../llama-server.bin
   Expected: no "not found" for llama/ggml libraries
4. Run: ~/.local/share/.../llama-server --version
   Expected: launches successfully, prints version
</verification>

<success_criteria>
1. build-runtime produces a bundle containing llama-server (wrapper), llama-server.bin (payload), and all required .so files
2. ldd on the payload binary shows zero unresolved llama/ggml/mtmd library references
3. Wrapper script launches the payload with LD_LIBRARY_PATH set to the bundle directory
4. Existing bundle discovery (validate_bundled_binary, probe_server_binary) works with the new wrapper+payload format
5. No regressions for non-bundled external binaries (which have no .bin sibling)
</success_criteria>

<output>
After completion, create `.planning/phases/12-runtime-packaging/12-runtime-packaging-01-SUMMARY.md`
</output>
