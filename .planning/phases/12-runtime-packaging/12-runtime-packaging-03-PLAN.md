---
phase: 12-runtime-packaging
plan: 03
type: execute
wave: 2
depends_on: ["12-runtime-packaging-01"]
files_modified:
  - bin/llama-model
  - install.sh
autonomous: true
requirements:
  - RUNTIME-06
  - RUNTIME-07
  - RUNTIME-08
user_setup: []

must_haves:
  truths:
    - "Validated bundled runtime matching preferred backend is selected first"
    - "LLAMA_SERVER_BIN is persisted to defaults.env after successful validation"
    - "CUDA-tagged model on CUDA host does not silently fall back to CPU-only binary"
    - "CPU runtime remains available as explicit fallback, not silent fallback"
  artifacts:
    - path: "bin/llama-model"
      provides: "select_valid_runtime() function, strengthened selection policy"
      contains:
        - "probe_server_binary"
        - "start_server"
        - "write_default_value"
    - path: "install.sh"
      provides: "LLAMA_SERVER_BIN persistence after runtime build"
      contains:
        - "build_runtime_during_install"
  key_links:
    - from: "probe_server_binary()"
      to: "validate_runtime_profile()"
      via: "validation results inform selection ranking"
    - from: "build_runtime_during_install()"
      to: "defaults.env"
      via: "persisted LLAMA_SERVER_BIN path after successful build"
    - from: "start_server()"
      to: "device/model config"
      via: "blocks CPU fallback when model requests CUDA"

---

<objective>
Strengthen runtime selection to prefer validated bundled runtimes, block incompatible CPU fallback, and persist the selected path.
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
@install.sh
@.planning/phases/12-runtime-packaging/12-runtime-packaging-01-PLAN.md
@.planning/phases/12-runtime-packaging/12-runtime-packaging-01-SUMMARY.md
@.planning/phases/12-runtime-packaging/12-runtime-packaging-02-PLAN.md
@.planning/phases/12-runtime-packaging/12-runtime-packaging-02-SUMMARY.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Rewrite probe_server_binary() selection policy</name>
  <files>bin/llama-model</files>
  <action>
    Modify probe_server_binary() (~line 1756) to implement a strict selection order:

    PRIORITY 1 — Explicit LLAMA_SERVER_BIN (if set and validates):
      If REQUESTED_LLAMA_SERVER_BIN is set, validate it using validate_runtime_profile().
      If validation passes, select it. If it fails, reject with clear message (don't silently skip to next).

    PRIORITY 2 — Validated bundled runtime matching preferred backend:
      Iterate through bundled runtimes in runtime/llama-server/.
      For each: validate_runtime_profile(profile_dir, expected_backend).
      Select the first one with validation_ok=yes and backend matching preferred.
      Preferred backend determined by detect_primary_build_backend() (cuda > vulkan > metal > cpu).

    PRIORITY 3 — Validated bundled CPU runtime:
      Same as priority 2, but only consider cpu backends.
      This is the fallback when no GPU bundle validates.

    PRIORITY 4 — Validated external binary with explicit warning:
      Only reach here if no bundled runtime validates.
      If an external binary is found (from PATH), select it but set:
        SELECTED_LLAMA_SERVER_STATUS="external-with-warning"
        SELECTED_LLAMA_SERVER_MESSAGE="No validated bundled runtime found; using external binary from PATH. Run 'llama-model build-runtime --backend auto' for best results."

    KEY GUARDRAIL — CUDA model on CUDA host with no validated CUDA runtime:
      In start_server(), after model is loaded, if model_device or LLAMA_SERVER_DEVICE contains "cuda" and no validated CUDA runtime was selected:
        - Do NOT silently select a CPU-only binary
        - Instead, die with: "Model requests CUDA but no validated CUDA runtime is available. Run 'llama-model build-runtime --backend cuda' to build one."

    This means the selection policy in probe_server_binary() should track whether a CUDA-capable runtime was found. If the host has CUDA capability and the selected binary is CPU-only, set a flag that start_server() can check.
  </action>
  <verify>
    <automated>bash -n bin/llama-model</automated>
  </verify>
  <done>Selection policy follows 4-tier priority with CUDA guardrail</done>
</task>

<task type="auto">
  <name>Task 2: Persist LLAMA_SERVER_BIN after validated runtime selection</name>
  <files>bin/llama-model</files>
  <action>
    Add a function persist_selected_runtime(bin_path) that writes LLAMA_SERVER_BIN to defaults.env:

    1. Call after successful runtime validation in probe_server_binary() when a bundled runtime is selected
    2. Use write_default_value() (existing function) to set LLAMA_SERVER_BIN=<absolute path>
    3. Only persist if:
       - The selected binary passed validation (validation_ok=yes)
       - The source is "bundled" (not external — we don't want to persist PATH binaries)
    4. Add to the defaults.env file: LLAMA_SERVER_BIN=<path to validated binary>

    Also update build_runtime_during_install() in install.sh (~line 77):
    - After a successful runtime build, call the persist function to write LLAMA_SERVER_BIN
    - This ensures the installed runtime is used on next startup without depending on PATH
    - Use the newly installed llama-model binary (already in place at $BIN_DIR/llama-model)

    The persistence happens in two places:
    1. During install (build_runtime_during_install) — first-time setup
    2. During runtime selection (probe_server_binary) — when user switches runtimes or rebuilds
  </action>
  <verify>
    <automated>bash -n bin/llama-model && bash -n install.sh</automated>
  </verify>
  <done>LLAMA_SERVER_BIN persisted to defaults.env after validated runtime selection</done>
</task>

</tasks>

<verification>
End-to-end test (manual):
1. Install fresh (or simulate): run build_runtime_during_install()
   Expected: LLAMA_SERVER_BIN written to defaults.env with absolute path to validated binary
2. Restart LMM: confirm it uses the persisted binary, not a PATH binary
3. Deliberately corrupt the CUDA bundle (remove a .so file):
   Expected: validation fails, CPU fallback selected only if no GPU runtime validates
4. Set device=cuda0 in model config with no validated CUDA runtime:
   Expected: startup blocked with clear error, no silent CPU fallback
</verification>

<success_criteria>
1. Selection follows 4-tier priority: explicit → bundled GPU → bundled CPU → external with warning
2. LLAMA_SERVER_BIN persisted to defaults.env after any validated bundled runtime selection
3. CUDA-tagged models on CUDA hosts never silently fall back to CPU-only binaries
4. CPU runtime remains available as explicit fallback (can be selected via --device or explicit config)
5. External binaries from PATH only selected with explicit warning when no bundled runtime validates
</success_criteria>

<output>
After completion, create `.planning/phases/12-runtime-packaging/12-runtime-packaging-03-SUMMARY.md`
</output>
