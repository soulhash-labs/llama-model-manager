---
phase: 14-opencode-glyphos-fast-lane
plan: 06
type: execute
wave: 5
depends_on: ["14-04", "14-05"]
files_modified:
  - scripts/integration_sync.py
  - web/app.py
  - web/app.js
  - tests/test_phase0_contracts.py
  - tests/test_portability.sh
  - docs/opencode-glyphos-fast-lane.md
autonomous: true
requirements: []
user_setup: []
---

<objective>
Align OpenCode and oh-my-openagent config sync with the fast GlyphOS lane and preserve manual cloud override hygiene.
</objective>

<context>
@.planning/phases/14-opencode-glyphos-fast-lane/RESEARCH.md
@scripts/integration_sync.py
@web/app.py
@web/app.js
@tests/test_phase0_contracts.py
@tests/test_portability.sh
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add fast GlyphOS provider sync support</name>
  <files>scripts/integration_sync.py, tests/test_phase0_contracts.py, tests/test_portability.sh</files>
  <action>
Teach integration sync to write a fast GlyphOS provider profile after the fast lane exists.

Expected provider shape:
- full GlyphOS provider points at `4010`
- fast GlyphOS provider points at `4011`
- raw `8081` is not the normal harness fallback for GlyphOS-required agents

Do not remove diagnostic direct-backend support if existing tests or operator workflows still use it.
  </action>
  <verify>
    <automated>python3 -m py_compile scripts/integration_sync.py</automated>
    <automated>pytest tests/test_phase0_contracts.py -k 'opencode or integration'</automated>
    <automated>bash tests/test_portability.sh</automated>
  </verify>
  <done>OpenCode sync can emit full and fast GlyphOS provider entries.</done>
</task>

<task type="auto">
  <name>Task 2: Validate OpenCode and oh-my-openagent model catalog references</name>
  <files>scripts/integration_sync.py, tests/test_phase0_contracts.py</files>
  <action>
Add validation so generated model IDs are checked against the live or supplied OpenCode model catalog before background tasks run.

Required behavior:
- missing installer-intended model IDs are detected
- remap guidance prefers available local/GlyphOS model IDs
- generated config does not silently point agents at unavailable models
  </action>
  <verify>
    <automated>pytest tests/test_phase0_contracts.py -k 'opencode or model'</automated>
  </verify>
  <done>No generated agent config points at unavailable model IDs without warning/remap.</done>
</task>

<task type="auto">
  <name>Task 3: Document manual cloud override and fast-lane operation</name>
  <files>docs/opencode-glyphos-fast-lane.md, web/app.py, web/app.js</files>
  <action>
Create a concise operator doc for:
- full vs fast GlyphOS lanes
- why raw `8081` is backend/internal
- how to use manual cloud override safely
- how to restore local-first config
- how to diagnose TTFB/context degradation from the UI
  </action>
  <verify>
    <manual>Review doc for local-first policy and no hidden cloud fallback.</manual>
  </verify>
  <done>Operators have a documented fast-lane and cloud-override workflow.</done>
</task>

</tasks>

<success_criteria>
- OpenCode can target fast GlyphOS for timeout-sensitive traffic.
- Full GlyphOS remains available.
- Raw llama.cpp is not required as a normal harness path.
- Model catalog mismatches are detected before generated config breaks agents.
- Cloud override remains explicit and reversible.
</success_criteria>

<output>
Create `.planning/phases/14-opencode-glyphos-fast-lane/14-opencode-glyphos-fast-lane-06-SUMMARY.md`.
</output>
