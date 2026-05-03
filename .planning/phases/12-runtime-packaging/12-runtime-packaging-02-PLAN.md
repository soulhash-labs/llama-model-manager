---
phase: 12-runtime-packaging
plan: 02
type: execute
wave: 2
depends_on: ["12-runtime-packaging-01"]
files_modified:
  - bin/llama-model
  - scripts/glyphos_openai_gateway.py
autonomous: true
requirements:
  - RUNTIME-04
  - RUNTIME-05
user_setup: []

must_haves:
  truths:
    - "Every discovered runtime profile is validated before being considered usable"
    - "Validation checks: binary exists, executable, ldd resolves libs, --version works, backend matches"
    - "Broken CUDA bundle is marked invalid BEFORE any launch attempt"
    - "Validation status appears in runtime profile state returned to dashboard"
  artifacts:
    - path: "bin/llama-model"
      provides: "validate_runtime_profile() function, runtime profile validation fields"
      contains:
        - "validate_bundled_binary"
        - "probe_server_binary"
        - "write_runtime_profiles_store"
    - path: "scripts/glyphos_openai_gateway.py"
      provides: "Validation results exposed in /api/state or doctor output"
      exports:
        - "validation_ok"
        - "status"
        - "missing_libs"
  key_links:
    - from: "validate_runtime_profile()"
      to: "probe_server_binary()"
      via: "validation runs during binary discovery, populates SELECTED_LLAMA_SERVER_STATUS"
    - from: "write_runtime_profiles_store()"
      to: "dashboard"
      via: "emitted profile JSON includes validation fields consumed by /api/state"

---

<objective>
Add runtime profile validation so discovered bundles are checked for usability before any launch attempt.
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
@.planning/phases/12-runtime-packaging/12-runtime-packaging-01-PLAN.md
@.planning/phases/12-runtime-packaging/12-runtime-packaging-01-SUMMARY.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add validate_runtime_profile() function to bin/llama-model</name>
  <files>bin/llama-model</files>
  <action>
    Add validate_runtime_profile(profile_dir, expected_backend) function after validate_bundled_binary().

    The function receives a runtime profile directory path (e.g., ~/.local/share/llama-model-manager/runtime/llama-server/linux-x86_64-cuda/) and the expected backend ("cuda", "vulkan", "metal", "cpu").

    Returns a structured result (printed as key=value pairs or stored in global variables):

    1. binary_exists: true/false — is llama-server present
    2. binary_executable: true/false — is it chmod +x
    3. ldd_ok: true/false — run ldd on the payload binary (resolve_bundle_payload_binary first), check for "not found" in libggml*/libllama*/libmtmd* lines
    4. missing_libs: comma-separated list of unresolved library names (empty if ldd_ok)
    5. version_ok: true/false — run llama-server --version, check exit code 0
    6. version_text: captured output from --version
    7. backend_detected: result of detect_external_binary_backend() on the payload
    8. backend_match: true/false — does backend_detected match expected_backend
    9. validation_ok: true only if all checks pass
    10. status: one of:
        - "compatible" — all checks pass
        - "invalid-missing-libs" — ldd failed
        - "invalid-not-executable" — chmod issue
        - "invalid-version-check" --version failed
        - "invalid-backend-mismatch" — detected backend != expected
        - "invalid-binary-missing" — no binary found
        - "unknown" — fallback

    Use validate_bundled_binary() as the starting point — it already does platform and dynamic link checks. Extend it rather than duplicate.

    Global variables to set (matching existing pattern):
    - VALIDATE_RUNTIME_OK="yes"/"no"
    - VALIDATE_RUNTIME_STATUS="compatible"/"invalid-..."
    - VALIDATE_RUNTIME_MESSAGE="descriptive message"
    - VALIDATE_RUNTIME_MISSING_LIBS="comma-separated list"
    - VALIDATE_RUNTIME_VERSION_TEXT="version output"
    - VALIDATE_RUNTIME_BACKEND_DETECTED="cuda"/"vulkan"/"metal"/"cpu"
  </action>
  <verify>
    <automated>bash -c 'source bin/llama-model 2>/dev/null; declare -f validate_runtime_profile | head -5'</automated>
  </verify>
  <done>validate_runtime_profile() function exists with all 10 validation fields</done>
</task>

<task type="auto">
  <name>Task 2: Integrate validation into write_runtime_profiles_store() and probe_server_binary()</name>
  <files>bin/llama-model</files>
  <action>
    1. Update write_runtime_profiles_store() (~line 2590):
       - For each discovered profile, call validate_runtime_profile(profile_dir, expected_backend)
       - Include validation fields in the emitted profile JSON/state:
         validation_ok, status, validation_message, missing_libs, version_text, binary_backend_detected
       - This makes validation results available to the dashboard via /api/state

    2. Update probe_server_binary() (~line 1756):
       - After binary selection, if the source is "bundled", call validate_runtime_profile()
       - If validation fails, set SELECTED_LLAMA_SERVER_STATUS to reflect the failure (e.g., "invalid-missing-libs")
       - Include the validation message in SELECTED_LLAMA_SERVER_MESSAGE

    3. Update show_doctor() (~line 3210):
       - If a runtime profile was discovered but failed validation, show:
         binary_status: invalid-missing-libs
         binary_message: "CUDA runtime invalid: missing libllama-common.so.0, libllama.so.0"
         binary_guidance: "Run llama-model build-runtime --backend cuda to rebuild"

    The key behavior change: a runtime profile with validation_ok=no is still discovered and reported, but marked invalid. It is not automatically excluded from selection (that's Plan 03), but it is clearly flagged so the selection logic can make informed decisions.
  </action>
  <verify>
    <automated>bash -n bin/llama-model</automated>
  </verify>
  <done>Runtime validation runs during discovery, results appear in profiles and doctor output</done>
</task>

</tasks>

<verification>
End-to-end test (manual):
1. Deliberately remove one .so file from a bundled runtime
2. Run: llama-model doctor
   Expected: binary_status shows "invalid-missing-libs", missing_libs lists the removed file
3. Verify the profile is still discoverable but clearly marked invalid
4. Run: llama-model build-runtime --backend cuda (after removing the broken bundle)
   Expected: new bundle validates as "compatible"
</verification>

<success_criteria>
1. validate_runtime_profile() checks all 6 dimensions: exists, executable, ldd, version, backend match, overall status
2. Broken bundles are marked invalid before any launch attempt
3. validation_ok, status, missing_libs, version_text, binary_backend_detected appear in runtime profile state
4. doctor output shows validation status and missing library details
5. No regressions in existing binary discovery for valid bundles
</success_criteria>

<output>
After completion, create `.planning/phases/12-runtime-packaging/12-runtime-packaging-02-SUMMARY.md`
</output>
