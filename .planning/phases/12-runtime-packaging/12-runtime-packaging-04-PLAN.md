---
phase: 12-runtime-packaging
plan: 04
type: execute
wave: 3
depends_on: ["12-runtime-packaging-02", "12-runtime-packaging-03"]
files_modified:
  - bin/llama-model
  - scripts/glyphos_openai_gateway.py
autonomous: true
requirements:
  - RUNTIME-09
  - RUNTIME-10
user_setup: []

must_haves:
  truths:
    - "Startup fails fast on runtime problems before model load is attempted"
    - "Structured diagnosis returned with category, message, and suggested fix"
    - "Doctor/startup flow shows runtime validation status before launch"
    - "Failure categories distinguish: missing libs, backend mismatch, version incompatible, runtime missing"
  artifacts:
    - path: "bin/llama-model"
      provides: "preflight_runtime_check() in start_server(), startup failure categories"
      contains:
        - "start_server"
        - "classify_startup_log_file"
        - "show_doctor"
    - path: "scripts/glyphos_openai_gateway.py"
      provides: "Runtime status exposed in /api/state for dashboard consumption"
      exports:
        - "runtime_validation_status"
        - "runtime_diagnosis"
  key_links:
    - from: "start_server()"
      to: "validate_runtime_profile()"
      via: "preflight check runs before llama-server fork, blocks launch if invalid"
    - from: "show_doctor()"
      to: "startup failure categories"
      via: "doctor output includes runtime_mismatch and runtime_missing_libs categories"

---

<objective>
Add startup preflight guardrails that fail early on runtime problems with structured diagnostics.
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
@scripts/glyphos_openai_gateway.py
@.planning/phases/12-runtime-packaging/12-runtime-packaging-01-PLAN.md
@.planning/phases/12-runtime-packaging/12-runtime-packaging-01-SUMMARY.md
@.planning/phases/12-runtime-packaging/12-runtime-packaging-02-PLAN.md
@.planning/phases/12-runtime-packaging/12-runtime-packaging-02-SUMMARY.md
@.planning/phases/12-runtime-packaging/12-runtime-packaging-03-PLAN.md
@.planning/phases/12-runtime-packaging/12-runtime-packaging-03-SUMMARY.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add preflight_runtime_check() to start_server()</name>
  <files>bin/llama-model</files>
  <action>
    Add a preflight check in start_server() (~line 2700, after model_path validation and before probe_server_binary):

    preflight_runtime_check(model_path, model_device, ngl, device):

    1. Check if probe_server_binary() was called and SELECTED_LLAMA_SERVER_STATUS is set
    2. If status indicates validation failure:
       - Map status to a failure category:
         "invalid-missing-libs" → "runtime-missing-libs"
         "invalid-backend-mismatch" → "runtime-backend-mismatch"
         "invalid-version-check" → "runtime-version-incompatible"
         "unavailable" → "runtime-missing"
       - Set STARTUP_FAILURE_CATEGORY and STARTUP_FAILURE_SUMMARY (existing globals)
       - Set STARTUP_FAILURE_ACTION (remediation guidance)
       - Print the structured failure and return 1 (do not attempt launch)

    3. If model_device or device contains "cuda" and SELECTED_LLAMA_SERVER_BACKEND is "cpu":
       - Set failure category: "runtime-backend-mismatch"
       - Message: "Model requests CUDA but selected llama-server binary is CPU-only"
       - Action: "Run 'llama-model build-runtime --backend cuda' to build a CUDA-enabled runtime"
       - Print and return 1

    4. If SELECTED_LLAMA_SERVER_SOURCE is "external-with-warning":
       - Print warning (not fatal): "Using external llama-server from PATH; no validated bundled runtime available"
       - Continue (user explicitly chose this or no alternative exists)

    Integrate this into the existing STARTUP_FAILURE_CATEGORY/STARTUP_FAILURE_SUMMARY/STARTUP_FAILURE_ACTION pattern used by classify_startup_log_file(). This means the preflight checks populate the same globals that the doctor output reads.

    The check runs BEFORE the llama-server fork, so the user sees the diagnosis immediately without waiting for a model-load crash.
  </action>
  <verify>
    <automated>bash -n bin/llama-model</automated>
  </verify>
  <done>Preflight check runs before launch, blocks startup with structured diagnosis on runtime failures</done>
</task>

<task type="auto">
  <name>Task 2: Expose runtime validation status in doctor and gateway state</name>
  <files>bin/llama-model</files>
  <action>
    1. Update show_doctor() (~line 3210) to include runtime validation fields:
       Add to the printf output:
       - runtime_validation_ok: yes/no
       - runtime_status: compatible/invalid-*/unknown
       - runtime_missing_libs: comma-separated list (if any)
       - runtime_version_text: version string (if available)
       - runtime_backend_detected: cuda/vulkan/metal/cpu

       These are populated by validate_runtime_profile() which runs during probe_server_binary().

    2. Update the gateway's /api/state response (scripts/glyphos_openai_gateway.py) to include runtime validation status:
       - If the gateway calls llama-model doctor or has its own runtime discovery, include the validation fields in the state JSON
       - This makes the data available to the dashboard UI (handled in Plan 05)

    3. Add startup_category to doctor output if preflight_runtime_check() set it:
       - startup_category: runtime-missing-libs / runtime-backend-mismatch / runtime-version-incompatible / runtime-missing
       - startup_diagnosis: human-readable summary
       - startup_suggested_fix: actionable remediation

    This ensures that both the CLI doctor output and the dashboard API return the same runtime validation information.
  </action>
  <verify>
    <automated>bash -n bin/llama-model</automated>
  </verify>
  <done>Doctor output and gateway state include runtime validation status and startup categories</done>
</task>

</tasks>

<verification>
End-to-end test (manual):
1. Corrupt the CUDA bundle (remove libggml-cuda.so)
2. Run: llama-model switch <model-alias>
   Expected: startup blocked immediately with "runtime-missing-libs" category, lists missing library
3. Set device=cuda0 with a CPU-only binary selected:
   Expected: startup blocked with "runtime-backend-mismatch", suggests build-runtime
4. Run: llama-model doctor
   Expected: shows runtime_status: invalid-missing-libs, runtime_missing_libs: libggml-cuda.so.0
5. With a valid bundle:
   Expected: startup proceeds normally, doctor shows runtime_status: compatible
</verification>

<success_criteria>
1. Preflight check runs before llama-server fork, blocks launch on runtime validation failures
2. Four failure categories cover all runtime problems: missing-libs, backend-mismatch, version-incompatible, missing
3. Doctor output shows runtime validation status and startup category with suggested fix
4. Gateway /api/state includes runtime validation fields for dashboard consumption
5. No "unknown model architecture" errors — runtime problems caught before model load
</success_criteria>

<output>
After completion, create `.planning/phases/12-runtime-packaging/12-runtime-packaging-04-SUMMARY.md`
</output>
