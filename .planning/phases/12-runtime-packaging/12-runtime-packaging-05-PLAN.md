---
phase: 12-runtime-packaging
plan: 05
type: execute
wave: 3
depends_on: ["12-runtime-packaging-02", "12-runtime-packaging-04"]
files_modified:
  - web/app.js
  - web/app.py
  - install.sh
autonomous: true
requirements:
  - RUNTIME-11
  - RUNTIME-12
  - RUNTIME-13
user_setup: []

must_haves:
  truths:
    - "Dashboard shows selected runtime path, backend, and validation status"
    - "Missing libraries listed explicitly (not vague 'CPU-only' warnings)"
    - "Installer post-build checks validate bundle completeness before claiming success"
    - "User can distinguish: missing libs, wrong binary, backend mismatch, genuine model incompatibility"
  artifacts:
    - path: "web/app.js"
      provides: "Runtime validation rendering in dashboard binary section"
      exports:
        - "renderRuntimeValidation"
      contains:
        - "renderStatus"
        - "binary summary rendering"
    - path: "web/app.py"
      provides: "Runtime validation data in dashboard state response"
      contains:
        - "api_state handler"
        - "_get_doctor_state"
    - path: "install.sh"
      provides: "Post-build ldd + --version validation"
      contains:
        - "build_runtime_during_install"
  key_links:
    - from: "web/app.js renderRuntimeValidation()"
      to: "gateway /api/state"
      via: "consumes runtime_validation_ok, runtime_status, runtime_missing_libs from state response"
    - from: "install.sh build_runtime_during_install()"
      to: "ldd + --version checks"
      via: "runs after build-runtime completes, validates bundle before claiming success"

---

<objective>
Add dashboard UI diagnostics for runtime validation and tighten installer post-build checks.
</objective>

<execution_context>
@/home/angelo/.config/opencode/get-shit-done/workflows/execute-plan.md
@/home/angelo/.config/opencode/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@web/app.js
@web/app.py
@install.sh
@.planning/phases/12-runtime-packaging/12-runtime-packaging-01-PLAN.md
@.planning/phases/12-runtime-packaging/12-runtime-packaging-01-SUMMARY.md
@.planning/phases/12-runtime-packaging/12-runtime-packaging-02-PLAN.md
@.planning/phases/12-runtime-packaging/12-runtime-packaging-02-SUMMARY.md
@.planning/phases/12-runtime-packaging/12-runtime-packaging-04-PLAN.md
@.planning/phases/12-runtime-packaging/12-runtime-packaging-04-SUMMARY.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add runtime validation rendering to dashboard (app.js)</name>
  <files>web/app.js</files>
  <action>
    Add renderRuntimeValidation(state) function and integrate into the existing binary status rendering.

    The function receives the dashboard state object which now includes:
    - binary_path, binary_source, binary_backend, binary_status, binary_message, binary_label
    - runtime_validation_ok, runtime_status, runtime_missing_libs, runtime_version_text, runtime_backend_detected
    - startup_category, startup_diagnosis, startup_suggested_fix

    Render a runtime validation card in the binary status section (near lines 220, 470, 623):

    VALID (runtime_validation_ok === "yes"):
      Show green indicator: "Runtime: compatible (cuda)" with binary path

    INVALID — missing libs (runtime_status === "invalid-missing-libs"):
      Show red indicator: "CUDA runtime invalid: missing libllama-common.so.0, libllama.so.0"
      Subtext: "Run 'llama-model build-runtime --backend cuda' to rebuild"

    INVALID — backend mismatch (runtime_status === "invalid-backend-mismatch"):
      Show red indicator: "Selected binary reports 'cpu' backend but profile expects 'cuda'"
      Subtext: "Run 'llama-model build-runtime --backend cuda' or set LLAMA_SERVER_BIN"

    INVALID — version (runtime_status === "invalid-version-check"):
      Show red indicator: "Runtime binary failed --version check"
      Subtext: "Binary may be corrupted or incompatible"

    INVALID — binary missing (runtime_status === "invalid-binary-missing"):
      Show red indicator: "No llama-server binary found in runtime profile"
      Subtext: "Run 'llama-model build-runtime --backend auto'"

    EXTERNAL WITH WARNING (binary_source === "external-with-warning"):
      Show yellow indicator: "Using external llama-server from PATH; no validated bundled runtime available"
      Subtext: "Run 'llama-model build-runtime --backend auto' for best results"

    STARTUP BLOCKED (startup_category is set):
      Show red banner at top of page:
        Category-specific icon + message
        "Suggested fix: {startup_suggested_fix}"

    Replace any existing vague warnings like "selected llama-server binary is CPU-only" with the new explicit messages.

    Add CSS classes for runtime validation states:
    - .runtime-status-compatible (green)
    - .runtime-status-invalid (red)
    - .runtime-status-warning (yellow)
  </action>
  <verify>
    <automated>node -e "const fs=require('fs'); const c=fs.readFileSync('web/app.js','utf8'); console.log(c.includes('renderRuntimeValidation') ? 'function found' : 'missing')"</automated>
  </verify>
  <done>renderRuntimeValidation() renders validation status with explicit error messages</done>
</task>

<task type="auto">
  <name>Task 2: Expose runtime validation in dashboard state API (app.py)</name>
  <files>web/app.py</files>
  <action>
    Update the /api/state handler (~line 1064 or wherever state is assembled) to include runtime validation fields.

    Parse the doctor output from llama-model doctor (or call the relevant functions directly) to extract:
    - runtime_validation_ok
    - runtime_status
    - runtime_missing_libs
    - runtime_version_text
    - runtime_backend_detected
    - startup_category
    - startup_diagnosis
    - startup_suggested_fix

    Include these in the JSON response alongside existing fields (binary_status, binary_message, etc.).

    Also update _get_doctor_state() (~line 3284) to pass through the runtime validation fields from the doctor output.

    This ensures the dashboard JavaScript has access to all runtime validation data for rendering.
  </action>
  <verify>
    <automated>python3 -c "import ast; ast.parse(open('web/app.py').read()); print('syntax ok')"</automated>
  </verify>
  <done>/api/state response includes runtime validation fields</done>
</task>

<task type="auto">
  <name>Task 3: Tighten installer post-build validation</name>
  <files>install.sh</files>
  <action>
    Update build_runtime_during_install() in install.sh (~line 77) to run post-build validation:

    After the build-runtime call succeeds, run these checks:

    1. ldd check:
       binary="$runtime_dir/llama-server.bin"
       missing="$(ldd "$binary" 2>&1 | grep 'not found' | grep -E 'lib(ggml|llama|mtmd)' || true)"
       if [[ -n "$missing" ]]; then
         printf 'post-install: runtime build produced incomplete bundle (missing libs: %s)\n' "$missing"
         printf 'post-install: runtime marked invalid, will not be auto-selected\n'
         mark_runtime_invalid=1
       fi

    2. --version check:
       if ! "$runtime_dir/llama-server" --version >/dev/null 2>&1; then
         printf 'post-install: runtime build failed --version check\n'
         mark_runtime_invalid=1
       fi

    3. Backend check:
       backend_in_profile="$(basename "$runtime_dir")"
       # Parse profile name like "linux-x86_64-cuda" to extract "cuda"
       expected_backend="${backend_in_profile##*-}"
       # Verify the binary actually has that backend (via ldd or detect_external_binary_backend)
       # For now, trust the build-backend flag — this is checked by validate_runtime_profile at runtime

    If mark_runtime_invalid=1:
      - Do NOT persist LLAMA_SERVER_BIN for this runtime
      - Print clear failure message with remediation
      - The runtime bundle still exists but is marked invalid by validation (Plan 02)

    If all checks pass:
      - Print "post-install: runtime build completed and validated successfully"
      - Persist LLAMA_SERVER_BIN as planned
  </action>
  <verify>
    <automated>bash -n install.sh</automated>
  </verify>
  <done>Installer validates bundle completeness before claiming success and persisting LLAMA_SERVER_BIN</done>
</task>

</tasks>

<verification>
End-to-end test (manual):
1. Run install.sh on a CUDA host with CUDA toolkit:
   Expected: post-build ldd passes, --version passes, LLAMA_SERVER_BIN persisted
2. Corrupt a bundled runtime (remove a .so file):
   Expected: dashboard shows "CUDA runtime invalid: missing libggml-cuda.so.0" in red
3. View dashboard with valid runtime:
   Expected: shows "Runtime: compatible (cuda)" in green with binary path
4. View dashboard with external PATH binary and no valid bundle:
   Expected: shows yellow warning about using external binary
5. Run install.sh with missing GPU build tools:
   Expected: CPU fallback built, validated, and used — no GPU claim made
</verification>

<success_criteria>
1. Dashboard shows explicit runtime validation status (compatible/invalid-*/warning) with colored indicators
2. Missing libraries listed by name in error messages (not vague "CPU-only" warnings)
3. User can distinguish four problem types on dashboard: missing libs, wrong binary, backend mismatch, model incompatibility
4. Installer runs ldd + --version checks after build, only persists LLAMA_SERVER_BIN if validation passes
5. /api/state includes all runtime validation fields consumed by the dashboard
</success_criteria>

<output>
After completion, create `.planning/phases/12-runtime-packaging/12-runtime-packaging-05-SUMMARY.md`
</output>
