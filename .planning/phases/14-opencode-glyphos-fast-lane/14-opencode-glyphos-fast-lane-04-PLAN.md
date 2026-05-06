---
phase: 14-opencode-glyphos-fast-lane
plan: 04
type: execute
wave: 3
depends_on: ["14-03"]
files_modified:
  - scripts/lmm_config.py
  - scripts/glyphos_openai_gateway.py
  - scripts/gateway/context_provider.py
  - scripts/gateway/routing_service.py
  - install.sh
  - config/defaults.env.example
  - tests/test_phase0_contracts.py
  - tests/test_portability.sh
autonomous: true
requirements: []
user_setup: []
---

<objective>
Introduce an explicit fast GlyphOS gateway lane on `4011` while preserving the full GlyphOS lane on `4010` and keeping raw llama.cpp on `8081` internal.
</objective>

<context>
@.planning/phases/14-opencode-glyphos-fast-lane/RESEARCH.md
@scripts/lmm_config.py
@scripts/glyphos_openai_gateway.py
@scripts/gateway/context_provider.py
@scripts/gateway/routing_service.py
@install.sh
@config/defaults.env.example
@tests/test_phase0_contracts.py
@tests/test_portability.sh
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add gateway lane configuration</name>
  <files>scripts/lmm_config.py, install.sh, config/defaults.env.example, tests/test_phase0_contracts.py, tests/test_portability.sh</files>
  <action>
Add explicit full/fast lane config with conservative defaults.

Expected config concepts:
- full gateway port remains `4010`
- fast gateway port defaults to `4011`
- fast lane can be enabled/disabled
- fast lane has stricter context preflight budget
- full lane behavior remains unchanged

Choose env names that match existing style and validate them centrally.
  </action>
  <verify>
    <automated>python3 -m py_compile scripts/lmm_config.py</automated>
    <automated>pytest tests/test_phase0_contracts.py -k 'lmm_config or gateway_server_factory'</automated>
    <automated>bash tests/test_portability.sh</automated>
  </verify>
  <done>Config supports full and fast gateway lanes without changing full-lane defaults.</done>
</task>

<task type="auto">
  <name>Task 2: Wire fast mode into gateway server creation</name>
  <files>scripts/glyphos_openai_gateway.py, scripts/gateway/context_provider.py, scripts/gateway/routing_service.py, tests/test_phase0_contracts.py</files>
  <action>
Add a gateway mode field such as `full` or `fast`.

Fast mode must:
- still use GlyphOS routing/prompt contracts
- preserve protocol normalization
- preserve route metadata
- preserve explicit `upstream_context`
- skip or sharply bound optional MCP retrieval

Full mode must keep existing behavior.
  </action>
  <verify>
    <automated>python3 -m py_compile scripts/glyphos_openai_gateway.py scripts/gateway/context_provider.py scripts/gateway/routing_service.py</automated>
    <automated>pytest tests/test_phase0_contracts.py -k 'gateway or context or stream'</automated>
  </verify>
  <done>Gateway can be instantiated as full or fast mode and reports the mode.</done>
</task>

<task type="auto">
  <name>Task 3: Add operational start/status support for fast lane</name>
  <files>bin/llama-model, install.sh, tests/test_portability.sh</files>
  <action>
If gateway start/status commands are managed by `bin/llama-model`, extend them to understand the fast lane without disrupting the existing gateway command.

Required behavior:
- existing gateway command continues to target full lane
- fast lane can be started/stopped/status-checked explicitly
- status output distinguishes full and fast lane
  </action>
  <verify>
    <automated>bash -n bin/llama-model</automated>
    <automated>bash tests/test_portability.sh</automated>
  </verify>
  <done>Operators can manage full and fast gateway lanes explicitly.</done>
</task>

</tasks>

<success_criteria>
- `4010` remains full GlyphOS.
- `4011` is available as fast GlyphOS when enabled.
- `8081` remains backend/internal.
- Fast mode remains GlyphOS-backed and does not bypass protocol/context/routing contracts.
</success_criteria>

<output>
Create `.planning/phases/14-opencode-glyphos-fast-lane/14-opencode-glyphos-fast-lane-04-SUMMARY.md`.
</output>
