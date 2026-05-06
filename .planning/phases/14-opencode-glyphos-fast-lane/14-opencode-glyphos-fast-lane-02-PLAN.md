---
phase: 14-opencode-glyphos-fast-lane
plan: 02
type: execute
wave: 1
depends_on: []
files_modified:
  - bin/llama-model
  - web/app.py
  - web/app.js
  - web/index.html
  - tests/test_portability.sh
  - tests/test_phase0_contracts.py
autonomous: true
requirements: []
user_setup: []
---

<objective>
Fix the GPU-layer warning path so CPU-only or invalid GPU runtimes do not pass misleading GPU offload settings and the UI reports the effective runtime posture.
</objective>

<context>
@.planning/phases/14-opencode-glyphos-fast-lane/RESEARCH.md
@bin/llama-model
@web/app.py
@web/app.js
@web/index.html
@tests/test_portability.sh
@tests/test_phase0_contracts.py
@.planning/phases/12-runtime-packaging/12-runtime-packaging-03-PLAN.md
@.planning/phases/12-runtime-packaging/12-runtime-packaging-04-PLAN.md
@.planning/phases/12-runtime-packaging/12-runtime-packaging-05-PLAN.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Lock the warning regression with tests</name>
  <files>tests/test_portability.sh</files>
  <action>
Add or tighten a portability test for this case:
- selected llama-server backend is `cpu`
- configured `LLAMA_SERVER_NGL` or model `ngl` requests GPU layers
- `start_server` must force effective `ngl=0`
- command output must explain CPU fallback and how to rebuild/select a GPU-capable runtime

The test should fail if `start_server` passes the requested GPU layer count through to a CPU-only runtime.
  </action>
  <verify>
    <automated>bash tests/test_portability.sh</automated>
  </verify>
  <done>CPU-only runtime plus GPU-layer request is covered by a regression test.</done>
</task>

<task type="auto">
  <name>Task 2: Make effective GPU-layer posture explicit in runtime output</name>
  <files>bin/llama-model</files>
  <action>
Update `start_server()` and related doctor/current output so the effective GPU-layer value is visible after runtime selection.

Required behavior:
- CPU backend forces effective `ngl=0`
- CUDA/Vulkan/Metal requested with no matching validated runtime gives an actionable diagnostic
- valid GPU backend preserves configured GPU layer posture
- output distinguishes requested GPU layers from effective GPU layers when they differ
  </action>
  <verify>
    <automated>bash -n bin/llama-model</automated>
    <automated>bash tests/test_portability.sh</automated>
  </verify>
  <done>Runtime output reports selected backend and effective GPU layer posture.</done>
</task>

<task type="auto">
  <name>Task 3: Surface effective GPU posture in the web UI</name>
  <files>web/app.py, web/app.js, web/index.html, tests/test_phase0_contracts.py</files>
  <action>
Expose selected backend and effective GPU-layer posture through the existing dashboard state.

The UI should make it clear whether the current run is:
- GPU-backed with configured offload
- CPU fallback with GPU layers forced to zero
- blocked because a CUDA/Vulkan/Metal device was requested without a validated matching runtime
  </action>
  <verify>
    <automated>python3 -m py_compile web/app.py</automated>
    <automated>pytest tests/test_phase0_contracts.py -k 'runtime or compatibility or gpu or ngl'</automated>
  </verify>
  <done>Dashboard state and rendering expose effective runtime/GPU posture.</done>
</task>

</tasks>

<success_criteria>
- The specific `no usable GPU found, --gpu-layers option will be ignored` class is prevented or made actionable.
- CPU fallback does not send misleading GPU-layer settings.
- GPU-capable runtime behavior remains unchanged.
- CLI and UI both expose effective backend and GPU-layer posture.
</success_criteria>

<output>
Create `.planning/phases/14-opencode-glyphos-fast-lane/14-opencode-glyphos-fast-lane-02-SUMMARY.md`.
</output>
