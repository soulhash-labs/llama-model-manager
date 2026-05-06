---
phase: 14-opencode-glyphos-fast-lane
plan: 05
type: execute
wave: 4
depends_on: ["14-04"]
files_modified:
  - web/app.py
  - web/app.js
  - web/index.html
  - web/styles.css
  - integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/api_client.py
  - integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/router.py
  - integrations/public-glyphos-ai-compute/tests/test_q2_flow.py
  - tests/test_phase0_contracts.py
autonomous: true
requirements: []
user_setup: []
---

<objective>
Expose operator-owned generation, streaming, lane, and provider diagnostics in the web UI without introducing hidden cloud fallback.
</objective>

<context>
@.planning/phases/14-opencode-glyphos-fast-lane/RESEARCH.md
@web/app.py
@web/app.js
@web/index.html
@web/styles.css
@integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/api_client.py
@integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/router.py
@integrations/public-glyphos-ai-compute/tests/test_q2_flow.py
@tests/test_phase0_contracts.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Surface effective full/fast lane diagnostics</name>
  <files>web/app.py, web/app.js, web/index.html, web/styles.css, tests/test_phase0_contracts.py</files>
  <action>
Add dashboard fields for:
- full gateway endpoint
- fast gateway endpoint
- backend endpoint
- active route mode
- recent TTFB / route target / context status from gateway telemetry
- context degraded/deferred state

Keep the existing dashboard style: dense operational cards, no marketing layout.
  </action>
  <verify>
    <automated>python3 -m py_compile web/app.py</automated>
    <automated>pytest tests/test_phase0_contracts.py -k 'gateway or web or context_glyphos_pipeline'</automated>
  </verify>
  <done>Dashboard shows enough state to diagnose full vs fast lane behavior.</done>
</task>

<task type="auto">
  <name>Task 2: Clarify operator policy and token precedence</name>
  <files>web/app.py, web/app.js, web/index.html, integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/api_client.py, integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/router.py, integrations/public-glyphos-ai-compute/tests/test_q2_flow.py</files>
  <action>
Make effective generation and streaming policy visible and operator-owned.

Policy rules:
- request override wins
- model/lane policy next
- operator default next
- hard safe fallback last

Do not make `32768` a hidden universal default for every provider. Treat it as an editable local preset where appropriate.
  </action>
  <verify>
    <automated>pytest integrations/public-glyphos-ai-compute/tests</automated>
    <automated>pytest tests/test_phase0_contracts.py -k 'gateway or opencode or defaults'</automated>
  </verify>
  <done>Effective policy source and values are visible and tested.</done>
</task>

<task type="auto">
  <name>Task 3: Preserve manual cloud override semantics</name>
  <files>web/app.py, web/app.js, integrations/public-glyphos-ai-compute/glyphos_ai/ai_compute/router.py, integrations/public-glyphos-ai-compute/tests/test_q2_flow.py</files>
  <action>
Ensure cloud provider status is visible without becoming an automatic fallback.

Required behavior:
- local-first remains default
- cloud routing requires explicit operator/request preference
- route metadata distinguishes manual cloud selection from fallback
  </action>
  <verify>
    <automated>pytest integrations/public-glyphos-ai-compute/tests</automated>
  </verify>
  <done>Cloud remains explicit and operator-controlled.</done>
</task>

</tasks>

<success_criteria>
- Web UI shows full/fast lane endpoints and effective policy.
- Operator can diagnose route/context/TTFB state from the dashboard.
- Cloud status is visible but not silently selected.
- Public GlyphOS AI compute tests remain green.
</success_criteria>

<output>
Create `.planning/phases/14-opencode-glyphos-fast-lane/14-opencode-glyphos-fast-lane-05-SUMMARY.md`.
</output>
